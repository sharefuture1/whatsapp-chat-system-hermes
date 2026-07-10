import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import http from 'node:http';
import { mkdtemp } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';

import { AccountManager } from '../src/account-manager.js';
import { createBridgeServer, listenBridgeServer } from '../src/server.js';

const token = 'test-internal-token';

function fakeSocket() {
  return {
    ev: new EventEmitter(),
    end() {},
    async logout() {},
    async sendPresenceUpdate() {},
    async sendMessage() { return { key: { id: 'wa-real-id' } }; },
  };
}

async function fixture({ ready = true } = {}) {
  const runtime = await mkdtemp(path.join(os.tmpdir(), 'bridge-http-'));
  const manager = new AccountManager({
    sessionRoot: path.join(runtime, 'sessions'),
    spoolRoot: path.join(runtime, 'spool'),
    mediaRoot: path.join(runtime, 'media'),
    socketFactory: async () => fakeSocket(),
  });
  await manager.initialize();
  let requestId = 0;
  const server = createBridgeServer({
    manager,
    internalToken: token,
    readyCheck: () => ready,
    requestIdFactory: () => `generated-${++requestId}`,
  });
  const address = await listenBridgeServer(server, { host: '127.0.0.1', port: 0 });
  return {
    manager,
    server,
    baseUrl: `http://127.0.0.1:${address.port}`,
    async close() { await new Promise((resolve) => server.close(resolve)); },
  };
}

async function request(baseUrl, route, {
  method = 'GET', body, auth = true, host, requestId,
} = {}) {
  const url = new URL(`${baseUrl}${route}`);
  const headers = {};
  if (auth) headers['X-Internal-Token'] = token;
  if (requestId !== undefined) headers['X-Request-ID'] = requestId;
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  const options = {
    hostname: url.hostname,
    port: url.port,
    path: `${url.pathname}${url.search}`,
    method,
    headers,
  };
  if (host) options.headers.Host = host;
  return new Promise((resolve, reject) => {
    const req = http.request(options, (res) => {
      const chunks = [];
      res.on('data', (chunk) => chunks.push(chunk));
      res.on('end', () => {
        const raw = Buffer.concat(chunks).toString('utf8');
        resolve({
          status: res.statusCode,
          headers: res.headers,
          async json() { return JSON.parse(raw); },
        });
      });
    });
    req.on('error', reject);
    if (body !== undefined) req.write(JSON.stringify(body));
    req.end();
  });
}

async function errorCode(response) {
  const payload = await response.json();
  assert.equal(typeof payload.error.message, 'string');
  assert.equal(typeof payload.error.retryable, 'boolean');
  assert.equal(payload.error.request_id, response.headers['x-request-id']);
  assert.deepEqual(payload.error.details, {});
  return payload.error.code;
}

test('NFR-OPS-002: live and ready are separate and unauthenticated', async () => {
  const fx = await fixture({ ready: false });
  try {
    assert.equal((await request(fx.baseUrl, '/health/live', { auth: false })).status, 200);
    const ready = await request(fx.baseUrl, '/health/ready', { auth: false });
    assert.equal(ready.status, 503);
    assert.equal(await errorCode(ready), 'not_ready');
  } finally { await fx.close(); }
});

test('API request tracing: every response echoes a legal X-Request-ID or generates one', async () => {
  const fx = await fixture({ ready: false });
  try {
    const echoed = await request(fx.baseUrl, '/health/live', { auth: false, requestId: 'req_valid-123' });
    assert.equal(echoed.headers['x-request-id'], 'req_valid-123');

    const generatedForMissing = await request(fx.baseUrl, '/health/live', { auth: false });
    assert.equal(generatedForMissing.headers['x-request-id'], 'generated-1');

    const generatedForInvalid = await request(fx.baseUrl, '/health/ready', {
      auth: false,
      requestId: 'invalid request id',
    });
    assert.equal(generatedForInvalid.status, 503);
    assert.equal(generatedForInvalid.headers['x-request-id'], 'generated-2');
  } finally { await fx.close(); }
});

test('SEC-002: every non-health API requires the exact internal token', async () => {
  const fx = await fixture();
  try {
    const missing = await request(fx.baseUrl, '/accounts', { method: 'POST', auth: false, body: {} });
    assert.equal(missing.status, 401);
    assert.equal(await errorCode(missing), 'unauthorized');
    const wrong = await fetch(`${fx.baseUrl}/accounts`, {
      method: 'POST', headers: { 'content-type': 'application/json', 'x-internal-token': 'wrong' }, body: '{}',
    });
    assert.equal(wrong.status, 401);
  } finally { await fx.close(); }
});

test('SEC-002: Host header prevents DNS rebinding and listener rejects non-loopback', async () => {
  const fx = await fixture();
  try {
    const response = await request(fx.baseUrl, '/health/live', { auth: false, host: 'evil.example' });
    assert.equal(response.status, 421);
    assert.equal(await errorCode(response), 'invalid_host');
    await assert.rejects(
      listenBridgeServer(createBridgeServer({ manager: fx.manager, internalToken: token }), { host: '0.0.0.0', port: 0 }),
      /loopback/,
    );
  } finally { await fx.close(); }
});

test('Bridge HTTP account lifecycle, status, QR, stop, logout, delete', async () => {
  const fx = await fixture();
  try {
    const created = await request(fx.baseUrl, '/accounts', {
      method: 'POST', body: { account_id: 'A', session_ref: 'account:A' },
    });
    assert.equal(created.status, 200);
    assert.equal((await created.json()).state, 'new');

    assert.equal((await request(fx.baseUrl, '/accounts/A/connect', { method: 'POST' })).status, 202);
    assert.equal((await request(fx.baseUrl, '/accounts/A/status')).status, 200);
    const accountSocket = fx.manager.get('A').socket;
    accountSocket.ev.emit('connection.update', { connection: 'connecting', qr: 'qr-secret' });
    await fx.manager.get('A').whenIdle();
    const qr = await request(fx.baseUrl, '/accounts/A/qr');
    assert.equal(qr.status, 200);
    assert.match((await qr.json()).qr_data_url, /^data:image\/png;base64,/);
    assert.equal((await request(fx.baseUrl, '/accounts/A/stop', { method: 'POST' })).status, 200);
    assert.equal((await request(fx.baseUrl, '/accounts/A/connect', { method: 'POST' })).status, 202);
    assert.equal((await request(fx.baseUrl, '/accounts/A/logout', { method: 'POST' })).status, 200);
    assert.equal((await request(fx.baseUrl, '/accounts/A?delete_session=false', { method: 'DELETE' })).status, 200);
  } finally { await fx.close(); }
});

test('send and typing validate bodies; send requires online and returns real message id', async () => {
  const fx = await fixture();
  try {
    fx.manager.createAccount({ account_id: 'A', session_ref: 'account:A' });
    let response = await request(fx.baseUrl, '/accounts/A/send', { method: 'POST', body: { chat_id: '', text: '' } });
    assert.equal(response.status, 400);
    assert.equal(await errorCode(response), 'invalid_body');

    response = await request(fx.baseUrl, '/accounts/A/send', {
      method: 'POST', body: { chat_id: '1@s.whatsapp.net', text: 'hi' },
    });
    assert.equal(response.status, 409);
    assert.equal(await errorCode(response), 'account_offline');

    await fx.manager.connect('A');
    fx.manager.get('A').socket.ev.emit('connection.update', { connection: 'open' });
    await fx.manager.get('A').whenIdle();
    response = await request(fx.baseUrl, '/accounts/A/send', {
      method: 'POST', body: { chat_id: '1@s.whatsapp.net', text: 'hi' },
    });
    assert.equal(response.status, 200);
    assert.deepEqual(await response.json(), {
      success: true, account_id: 'A', chat_id: '1@s.whatsapp.net', message_id: 'wa-real-id',
    });
    assert.equal((await request(fx.baseUrl, '/accounts/A/typing', {
      method: 'POST', body: { chat_id: '1@s.whatsapp.net', typing: true },
    })).status, 200);
  } finally { await fx.close(); }
});

test('NFR-OPS-002: server applies bounded HTTP timeouts', async () => {
  const fx = await fixture();
  try {
    assert.equal(fx.server.requestTimeout, 30_000);
    assert.equal(fx.server.headersTimeout, 15_000);
    assert.equal(fx.server.keepAliveTimeout, 5_000);
  } finally { await fx.close(); }
});

test('send-media rejects absolute/traversal refs before explicit not_implemented', async () => {
  const fx = await fixture();
  try {
    fx.manager.createAccount({ account_id: 'A', session_ref: 'account:A' });
    for (const mediaRef of ['/etc/passwd', '../secret']) {
      const invalid = await request(fx.baseUrl, '/accounts/A/send-media', {
        method: 'POST', body: { chat_id: '1@s.whatsapp.net', media_type: 'image', media_ref: mediaRef },
      });
      assert.equal(invalid.status, 400);
      assert.equal(await errorCode(invalid), 'invalid_media_ref');
    }
    const valid = await request(fx.baseUrl, '/accounts/A/send-media', {
      method: 'POST', body: { chat_id: '1@s.whatsapp.net', media_type: 'image', media_ref: 'media-1' },
    });
    assert.equal(valid.status, 501);
    assert.equal(await errorCode(valid), 'not_implemented');
  } finally { await fx.close(); }
});
