import assert from 'node:assert/strict';
import { mkdtemp, readdir } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';

import { FileSpool } from '../src/events/file-spool.js';
import { EventSink } from '../src/events/event-sink.js';

function event(eventId = 'evt-1') {
  return {
    event_id: eventId,
    event_type: 'account.connected',
    account_id: 'A',
    occurred_at: '2026-07-10T00:00:00.000Z',
    sequence: 1,
    payload: { state: 'online' },
  };
}

async function setup(fetchImpl, options = {}) {
  const root = await mkdtemp(path.join(os.tmpdir(), 'event-sink-'));
  const spool = new FileSpool({ root, accountId: 'A', now: options.now });
  const sink = new EventSink({
    spool,
    token: 'internal-secret',
    fetchImpl,
    timeoutMs: options.timeoutMs ?? 20,
    backoff: options.backoff ?? (() => 0),
    now: options.now,
  });
  await sink.initialize();
  return { root, spool, sink };
}

async function count(root, state) {
  return (await readdir(path.join(root, 'A', state))).length;
}

function response(status, body = {}) {
  return { status, async json() { return body; } };
}

test('API-EVENT: enqueue persists before POST and sends required URL/headers', async () => {
  let persistedAtPost = false;
  let seen;
  const { root, sink } = await setup(async (url, init) => {
    persistedAtPost = await count(root, 'inflight') === 1;
    seen = { url, init };
    return response(200, { accepted: true, duplicate: false, event_id: 'evt-1' });
  });

  await sink.enqueue(event());
  assert.equal(persistedAtPost, true);
  assert.equal(seen.url, 'http://127.0.0.1:8792/internal/events/whatsapp');
  assert.equal(seen.init.headers['X-Internal-Token'], 'internal-secret');
  assert.equal(seen.init.headers['X-Request-ID'], 'evt-1');
  assert.deepEqual(JSON.parse(seen.init.body), event());
  assert.equal(await count(root, 'pending'), 0);
  assert.equal(await count(root, 'inflight'), 0);
});

test('API-EVENT: webhook 500 and 401 retain the event for retry', async () => {
  for (const status of [500, 401, 403, 409]) {
    const { root, sink } = await setup(async () => response(status));
    await sink.enqueue(event(`evt-${status}`));
    assert.equal(await count(root, 'pending'), 1, `status ${status}`);
    assert.equal(await count(root, 'inflight'), 0);
  }
});

test('API-EVENT: timeout/network errors retain the event', async () => {
  const { root, sink } = await setup((_url, { signal }) => new Promise((resolve, reject) => {
    signal.addEventListener('abort', () => reject(new Error('aborted')));
  }), { timeoutMs: 5 });
  await sink.enqueue(event('timeout'));
  assert.equal(await count(root, 'pending'), 1);
});

test('API-EVENT: duplicate=true and duplicate=false accepted responses both complete', async () => {
  for (const duplicate of [true, false]) {
    const { root, sink } = await setup(async () => response(200, {
      accepted: true,
      duplicate,
      event_id: `duplicate-${duplicate}`,
    }));
    await sink.enqueue(event(`duplicate-${duplicate}`));
    assert.equal(await count(root, 'pending'), 0);
    assert.equal(await count(root, 'inflight'), 0);
  }
});

test('API-EVENT: HTTP 422 moves event to dead-letter', async () => {
  const { root, sink } = await setup(async () => response(422));
  await sink.enqueue(event('schema-error'));
  assert.equal(await count(root, 'pending'), 0);
  assert.equal(await count(root, 'inflight'), 0);
  assert.equal(await count(root, 'dead'), 1);
});

test('API-EVENT: restart replays an event retained after failure', async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), 'event-replay-'));
  const firstSpool = new FileSpool({ root, accountId: 'A' });
  const firstSink = new EventSink({
    spool: firstSpool,
    token: 'token',
    fetchImpl: async () => response(500),
    backoff: () => 0,
  });
  await firstSink.initialize();
  await firstSink.enqueue(event('replay'));
  assert.equal(await count(root, 'pending'), 1);

  let calls = 0;
  const restarted = new EventSink({
    spool: new FileSpool({ root, accountId: 'A' }),
    token: 'token',
    fetchImpl: async () => {
      calls += 1;
      return response(200, { accepted: true, duplicate: false, event_id: 'replay' });
    },
  });
  await restarted.start();
  await restarted.stop();
  assert.equal(calls, 1);
  assert.equal(await count(root, 'pending'), 0);
});

test('API-EVENT: injected exponential backoff controls retry availability', async () => {
  let now = 1_000;
  let calls = 0;
  const { spool, sink } = await setup(async () => {
    calls += 1;
    return response(calls === 1 ? 500 : 200, { accepted: true, duplicate: false, event_id: 'backoff' });
  }, { now: () => now, backoff: (attempt) => 100 * (2 ** (attempt - 1)) });

  await sink.enqueue(event('backoff'));
  assert.equal(calls, 1);
  await sink.flushOnce();
  assert.equal(calls, 1);
  now = 1_100;
  await sink.flushOnce();
  assert.equal(calls, 2);
  assert.equal(await spool.claim(), null);
});

test('API-EVENT: concurrent flushOnce calls never duplicate the same claim', async () => {
  let calls = 0;
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  const { sink } = await setup(async () => {
    calls += 1;
    await gate;
    return response(200, { accepted: true, duplicate: false, event_id: 'once' });
  });
  await sink.spool.append(event('once'));
  const one = sink.flushOnce();
  const two = sink.flushOnce();
  release();
  await Promise.all([one, two]);
  assert.equal(calls, 1);
});

test('SEC-002: EventSink fails closed without an internal token', async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), 'event-token-'));
  const spool = new FileSpool({ root, accountId: 'A' });
  assert.throws(() => new EventSink({ spool, token: '' }), /token/i);
});
