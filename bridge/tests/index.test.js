import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { mkdir, mkdtemp, readdir, readFile, writeFile } from 'node:fs/promises';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';

import { installGracefulShutdown, startBridge } from '../src/index.js';

test('NFR-OPS-002: SIGTERM/SIGINT close listener and account sessions once', async () => {
  const processRef = new EventEmitter();
  processRef.exitCode = undefined;
  const calls = [];
  const server = { close(callback) { calls.push('server.close'); callback(); } };
  const manager = { async closeAll() { calls.push('manager.closeAll'); } };
  const shutdown = installGracefulShutdown({ processRef, server, manager });

  processRef.emit('SIGTERM');
  processRef.emit('SIGINT');
  await shutdown.done;

  assert.deepEqual(calls, ['server.close', 'manager.closeAll']);
  assert.equal(processRef.exitCode, 0);
});

test('API-EVENT: real startBridge scans safe spool accounts and replays without registration/socket', async () => {
  const runtime = await mkdtemp(path.join(os.tmpdir(), 'bridge-start-replay-'));
  const spoolRoot = path.join(runtime, 'spool');
  const pending = path.join(spoolRoot, 'A', 'pending');
  await Promise.all([
    mkdir(pending, { recursive: true }),
    mkdir(path.join(spoolRoot, 'A', 'inflight'), { recursive: true }),
    mkdir(path.join(spoolRoot, 'A', 'dead'), { recursive: true }),
    mkdir(path.join(spoolRoot, 'unsafe account'), { recursive: true }),
  ]);
  const event = {
    event_id: 'restart-event', event_type: 'account.connected', account_id: 'A',
    occurred_at: '2026-07-10T00:00:00.000Z', sequence: 7, payload: { state: 'online' },
  };
  await writeFile(path.join(pending, `${'a'.repeat(64)}.json`), `${JSON.stringify({
    event, attempt: 0, available_at: 0, last_error: null,
  })}\n`);

  const received = [];
  const receiver = http.createServer((request, response) => {
    let body = '';
    request.on('data', (chunk) => { body += chunk; });
    request.on('end', () => {
      received.push(JSON.parse(body));
      response.writeHead(200, { 'Content-Type': 'application/json' });
      response.end(JSON.stringify({ accepted: true, duplicate: false, event_id: 'restart-event' }));
    });
  });
  await new Promise((resolve) => receiver.listen(0, '127.0.0.1', resolve));
  const receiverPort = receiver.address().port;
  const started = await startBridge({
    WHATSAPP_BRIDGE_INTERNAL_TOKEN: 'test-token',
    BRIDGE_RUNTIME_ROOT: runtime,
    BRIDGE_PORT: '0',
    WHATSAPP_EVENT_URL: `http://127.0.0.1:${receiverPort}/internal/events/whatsapp`,
  });
  try {
    assert.deepEqual(received, [event]);
    assert.equal(started.manager.sessions.size, 0);
    assert.deepEqual(await readdir(pending), []);
  } finally {
    await started.gracefulShutdown.shutdown();
    await new Promise((resolve) => receiver.close(resolve));
  }
});

test('API-EVENT P0: startBridge transfers one replay sink owner to POST /accounts without duplicate sequence/claim', async () => {
  const runtime = await mkdtemp(path.join(os.tmpdir(), 'bridge-start-owner-'));
  const spoolRoot = path.join(runtime, 'spool');
  await Promise.all([
    mkdir(path.join(spoolRoot, 'A', 'pending'), { recursive: true }),
    mkdir(path.join(spoolRoot, 'A', 'inflight'), { recursive: true }),
    mkdir(path.join(spoolRoot, 'A', 'dead'), { recursive: true }),
  ]);
  await writeFile(path.join(spoolRoot, 'A', 'sequence'), '7\n');
  const started = await startBridge({
    WHATSAPP_BRIDGE_INTERNAL_TOKEN: 'test-token',
    BRIDGE_RUNTIME_ROOT: runtime,
    BRIDGE_PORT: '0',
  });
  try {
    const port = started.server.address().port;
    const response = await fetch(`http://127.0.0.1:${port}/accounts`, {
      method: 'POST',
      headers: {
        'content-type': 'application/json',
        'x-internal-token': 'test-token',
      },
      body: JSON.stringify({ account_id: 'A', session_ref: 'account:A' }),
    });
    assert.equal(response.status, 200);
    const session = started.manager.get('A');
    assert.equal(session.eventSink, started.replaySinks.get('A'));
    const sequences = await Promise.all(Array.from({ length: 20 }, () => session.eventSink.nextSequence()));
    assert.deepEqual(sequences.slice().sort((a, b) => a - b), Array.from({ length: 20 }, (_, i) => i + 8));
    assert.equal(await readFile(path.join(spoolRoot, 'A', 'sequence'), 'utf8'), '27\n');
    assert.equal((await readdir(path.join(spoolRoot, 'A', 'inflight'))).length, 0);
  } finally {
    await started.gracefulShutdown.shutdown();
  }
});
