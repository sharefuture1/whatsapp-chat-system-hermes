import assert from 'node:assert/strict';
import { access, mkdir, mkdtemp, readFile, readdir, stat, writeFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';

import { FileSpool } from '../src/events/file-spool.js';

function event(accountId, eventId, sequence = 1) {
  return {
    event_id: eventId,
    event_type: 'account.connected',
    account_id: accountId,
    occurred_at: '2026-07-10T00:00:00.000Z',
    sequence,
    payload: { state: 'online' },
  };
}

async function root() {
  return mkdtemp(path.join(os.tmpdir(), 'bridge-spool-'));
}

async function names(directory) {
  return (await readdir(directory)).sort();
}

test('API-EVENT: append is atomic, durable, idempotent, and uses a safe hashed filename', async () => {
  const spoolRoot = await root();
  const spool = new FileSpool({ root: spoolRoot, accountId: 'A' });
  await spool.initialize();
  const unsafeId = '../../event/with spaces?and=chars';
  const first = await spool.append(event('A', unsafeId));
  const second = await spool.append(event('A', unsafeId));

  assert.equal(first.key, second.key);
  assert.match(first.key, /^[a-f0-9]{64}\.json$/);
  assert.equal(first.key.includes('..'), false);
  assert.deepEqual(await names(path.join(spoolRoot, 'A', 'pending')), [first.key]);
  assert.deepEqual(await names(path.join(spoolRoot, 'A', 'inflight')), []);
  assert.equal(JSON.parse(await readFile(path.join(spoolRoot, 'A', 'pending', first.key), 'utf8')).event.event_id, unsafeId);
});

test('API-EVENT: append rejects the same event_id with a different canonical envelope in every queue state', async () => {
  for (const state of ['pending', 'inflight', 'dead']) {
    const spool = new FileSpool({ root: await root(), accountId: 'A' });
    await spool.initialize();
    const original = event('A', `identity-${state}`);
    original.payload = { nested: { b: 2, a: 1 }, state: 'online' };
    await spool.append(original);
    if (state !== 'pending') {
      const claim = await spool.claim();
      if (state === 'dead') await spool.deadLetter(claim, { error: 'schema' });
    }

    const reordered = {
      payload: { state: 'online', nested: { a: 1, b: 2 } },
      sequence: original.sequence,
      occurred_at: original.occurred_at,
      account_id: original.account_id,
      event_type: original.event_type,
      event_id: original.event_id,
    };
    assert.equal((await spool.append(reordered)).state, state);
    await assert.rejects(
      spool.append({ ...original, payload: { state: 'offline' } }),
      { code: 'event_identity_conflict' },
    );
  }
});

test('DATA-003: account A/B queues and directories are isolated and traversal account IDs are rejected', async () => {
  const spoolRoot = await root();
  const a = new FileSpool({ root: spoolRoot, accountId: 'A' });
  const b = new FileSpool({ root: spoolRoot, accountId: 'B' });
  await Promise.all([a.initialize(), b.initialize()]);
  await a.append(event('A', 'same-id'));
  await b.append(event('B', 'same-id'));

  assert.equal((await a.claim()).event.account_id, 'A');
  assert.equal((await b.claim()).event.account_id, 'B');
  assert.throws(() => new FileSpool({ root: spoolRoot, accountId: '../escape' }), /account/i);
  await assert.rejects(a.append(event('B', 'wrong-account')), /account/i);
});

test('API-EVENT: claim is atomic, release records attempts, and complete removes inflight', async () => {
  let now = 1_000;
  const spool = new FileSpool({ root: await root(), accountId: 'A', now: () => now });
  await spool.initialize();
  await spool.append(event('A', 'claim-me'));

  const [one, two] = await Promise.all([spool.claim(), spool.claim()]);
  const claim = one || two;
  assert.ok(claim);
  assert.equal(one === null || two === null, true);
  await spool.release(claim, { error: 'HTTP 500', delayMs: 50 });
  assert.equal(await spool.claim(), null);
  now = 1_050;
  const retried = await spool.claim();
  assert.equal(retried.attempt, 1);
  assert.equal(retried.last_error, 'HTTP 500');
  await spool.complete(retried);
  assert.equal(await spool.claim(), null);
});

test('API-EVENT: startup recovers inflight records back to pending', async () => {
  const spoolRoot = await root();
  const first = new FileSpool({ root: spoolRoot, accountId: 'A' });
  await first.initialize();
  await first.append(event('A', 'restart'));
  const claimed = await first.claim();
  assert.ok(claimed);

  const restarted = new FileSpool({ root: spoolRoot, accountId: 'A' });
  await restarted.initialize();
  const recovered = await restarted.claim();
  assert.equal(recovered.event.event_id, 'restart');
  assert.equal(recovered.attempt, 0);
});

test('API-EVENT: corrupt JSON is isolated in dead and does not block valid events', async () => {
  const spoolRoot = await root();
  const pending = path.join(spoolRoot, 'A', 'pending');
  await mkdir(pending, { recursive: true });
  await writeFile(path.join(pending, 'corrupt.json'), '{not-json');
  const spool = new FileSpool({ root: spoolRoot, accountId: 'A' });
  await spool.initialize();
  await spool.append(event('A', 'valid'));

  const claimed = await spool.claim();
  assert.equal(claimed.event.event_id, 'valid');
  assert.deepEqual(await names(path.join(spoolRoot, 'A', 'dead')), ['corrupt.json']);
});

test('SEC-004: account spool directories are mode 0700', async () => {
  const spoolRoot = await root();
  const spool = new FileSpool({ root: spoolRoot, accountId: 'A' });
  await spool.initialize();
  for (const part of ['', 'pending', 'inflight', 'dead']) {
    assert.equal((await stat(path.join(spoolRoot, 'A', part))).mode & 0o777, 0o700);
  }
});

test('API-EVENT: sequence remains monotonic for an account across restart', async () => {
  const spoolRoot = await root();
  const first = new FileSpool({ root: spoolRoot, accountId: 'A' });
  await first.initialize();
  assert.equal(await first.nextSequence(), 1);
  assert.equal(await first.nextSequence(), 2);
  const restarted = new FileSpool({ root: spoolRoot, accountId: 'A' });
  await restarted.initialize();
  assert.equal(await restarted.nextSequence(), 3);
});

test('API-EVENT: claim follows sequence then enqueue order, never hashed filename order', async () => {
  const spool = new FileSpool({ root: await root(), accountId: 'A' });
  await spool.initialize();
  await spool.append(event('A', 'hash-sorts-first-but-sequence-last', 20));
  await spool.append(event('A', 'hash-sorts-last-but-sequence-first', 10));
  await spool.append(event('A', 'same-sequence-first', 30));
  await spool.append(event('A', 'same-sequence-second', 30));

  const claimed = [];
  for (let index = 0; index < 4; index += 1) {
    const item = await spool.claim();
    claimed.push(item.event.event_id);
    await spool.complete(item);
  }
  assert.deepEqual(claimed, [
    'hash-sorts-last-but-sequence-first',
    'hash-sorts-first-but-sequence-last',
    'same-sequence-first',
    'same-sequence-second',
  ]);
});

test('API-EVENT: dead-letter moves the claimed record out of inflight', async () => {
  const spoolRoot = await root();
  const spool = new FileSpool({ root: spoolRoot, accountId: 'A' });
  await spool.initialize();
  const appended = await spool.append(event('A', 'bad-schema'));
  const claimed = await spool.claim();
  await spool.deadLetter(claimed, { error: 'HTTP 422' });
  await assert.rejects(access(path.join(spoolRoot, 'A', 'inflight', appended.key)));
  assert.deepEqual(await names(path.join(spoolRoot, 'A', 'dead')), [appended.key]);
});
