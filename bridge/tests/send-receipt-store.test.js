import assert from 'node:assert/strict';
import { mkdtemp, rm, stat } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';

import { SendReceiptStore } from '../src/send-receipt-store.js';

async function withTempDir(run) {
  const directory = await mkdtemp(path.join(os.tmpdir(), 'wa-send-receipts-'));
  try {
    await run(directory);
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
}

test('send receipts persist with private permissions and reload after restart', async () => {
  await withTempDir(async (directory) => {
    const store = new SendReceiptStore(directory);
    await store.start();
    await store.put('reply:client-1', 'wa-message-1');

    assert.equal(store.get('reply:client-1'), 'wa-message-1');
    const mode = (await stat(store.filePath)).mode & 0o777;
    assert.equal(mode, 0o600);

    const reloaded = new SendReceiptStore(directory);
    await reloaded.start();
    assert.equal(reloaded.get('reply:client-1'), 'wa-message-1');
  });
});

test('send receipt queue recovers after one transient file write failure', async () => {
  await withTempDir(async (directory) => {
    const store = new SendReceiptStore(directory);
    await store.start();
    const validPath = store.filePath;

    store.filePath = directory;
    await assert.rejects(store.put('reply:first', 'wa-first'));

    store.filePath = validPath;
    await store.put('reply:second', 'wa-second');
    assert.equal(store.get('reply:second'), 'wa-second');

    const reloaded = new SendReceiptStore(directory);
    await reloaded.start();
    assert.equal(reloaded.get('reply:first'), 'wa-first');
    assert.equal(reloaded.get('reply:second'), 'wa-second');
  });
});

test('invalid send receipt keys are rejected before touching disk', async () => {
  await withTempDir(async (directory) => {
    const store = new SendReceiptStore(directory);
    await store.start();

    assert.throws(
      () => store.validateKey('bad key with spaces'),
      error => error?.code === 'invalid_idempotency_key',
    );
    await assert.rejects(
      store.put('*invalid*', 'wa-message'),
      error => error?.code === 'invalid_idempotency_key',
    );
  });
});
