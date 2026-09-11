import assert from 'node:assert/strict';
import { mkdtemp, readdir } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';

import { EventSink } from '../src/events/event-sink.js';
import { FileSpool } from '../src/events/file-spool.js';

function receiptEvent() {
  return {
    event_id: 'legacy-delivered-receipt',
    event_type: 'message.delivered',
    account_id: 'A',
    occurred_at: '2026-09-12T00:00:00.000Z',
    sequence: 310,
    payload: {
      wa_message_id: 'missing-parent-message',
      timestamp: '2026-09-12T00:00:00.000Z',
      error_code: null,
      error_message: null,
    },
  };
}

function response(status, body = {}) {
  return { status, async json() { return body; } };
}

async function count(root, state) {
  return (await readdir(path.join(root, 'A', state))).length;
}

test('API-EVENT: explicit message_not_found stops retrying after a bounded grace window', async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), 'event-missing-message-'));
  const spool = new FileSpool({ root, accountId: 'A' });
  let calls = 0;
  const sink = new EventSink({
    spool,
    token: 'internal-secret',
    fetchImpl: async () => {
      calls += 1;
      return response(409, {
        error: { code: 'message_not_found', retryable: true },
      });
    },
    backoff: () => 0,
  });
  await sink.initialize();
  await spool.append(receiptEvent());

  for (let attempt = 0; attempt < 11; attempt += 1) {
    await sink.flushOnce();
  }
  assert.equal(await count(root, 'pending'), 1);
  assert.equal(await count(root, 'dead'), 0);

  await sink.flushOnce();
  assert.equal(calls, 12);
  assert.equal(await count(root, 'pending'), 0);
  assert.equal(await count(root, 'inflight'), 0);
  assert.equal(await count(root, 'dead'), 1);
});

test('API-EVENT: ambiguous retryable 409 remains retained beyond the message-not-found budget', async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), 'event-ambiguous-409-'));
  const spool = new FileSpool({ root, accountId: 'A' });
  const sink = new EventSink({
    spool,
    token: 'internal-secret',
    fetchImpl: async () => response(409, {
      error: { code: 'temporary_conflict', retryable: true },
    }),
    backoff: () => 0,
  });
  await sink.initialize();
  await spool.append({ ...receiptEvent(), event_id: 'ambiguous-409' });

  for (let attempt = 0; attempt < 15; attempt += 1) {
    await sink.flushOnce();
  }
  assert.equal(await count(root, 'pending'), 1);
  assert.equal(await count(root, 'dead'), 0);
});
