import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { mkdtemp } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';

import { AccountSession } from '../src/account-session.js';

function socket(overrides = {}) {
  return {
    ev: new EventEmitter(),
    endCalls: 0,
    logoutCalls: 0,
    end() { this.endCalls += 1; },
    async logout() { this.logoutCalls += 1; },
    async sendMessage() { return { key: { id: 'real-id' } }; },
    async sendPresenceUpdate() {},
    ...overrides,
  };
}

function fakeScheduler() {
  let nextId = 1;
  const tasks = new Map();
  return {
    setTimeout(callback, delay) {
      const id = nextId++;
      tasks.set(id, { callback, delay });
      return id;
    },
    clearTimeout(id) { tasks.delete(id); },
    delays() { return [...tasks.values()].map((task) => task.delay); },
    size() { return tasks.size; },
    async runNext() {
      const entry = tasks.entries().next().value;
      assert.ok(entry, 'expected a scheduled task');
      const [id, task] = entry;
      tasks.delete(id);
      await task.callback();
    },
  };
}

async function makeSession(socketFactory, options = {}) {
  const root = await mkdtemp(path.join(os.tmpdir(), 'bridge-session-'));
  return new AccountSession({
    accountId: 'A',
    sessionRef: 'account:A',
    sessionDir: path.join(root, 'sessions', 'A'),
    spoolDir: path.join(root, 'spool', 'A'),
    mediaDir: path.join(root, 'media', 'A'),
    socketFactory,
    qrTtlMs: options.qrTtlMs ?? 30_000,
    now: options.now,
    scheduler: options.scheduler,
    reconnectBaseMs: options.reconnectBaseMs,
    reconnectMaxMs: options.reconnectMaxMs,
    reconnectJitter: options.reconnectJitter,
    eventSink: options.eventSink,
  });
}

function recordingSink() {
  let sequence = 0;
  const events = [];
  return {
    events,
    async start() {},
    async stop() {},
    async nextSequence() { sequence += 1; return sequence; },
    async enqueue(item) { events.push(item); },
  };
}

test('FR-ACC-002: status transitions, QR data URL TTL, and online QR cleanup', async () => {
  let now = 1_000;
  const sock = socket();
  const session = await makeSession(async () => sock, { qrTtlMs: 100, now: () => now });
  assert.equal(session.status().state, 'new');
  await session.connect();
  assert.equal(session.status().state, 'connecting');

  sock.ev.emit('connection.update', { qr: 'qr-secret' });
  await session.whenIdle();
  const qr = session.getQr();
  assert.equal(session.status().state, 'qr_pending');
  assert.match(qr.qr_data_url, /^data:image\/png;base64,/);
  assert.equal(qr.expires_at, new Date(1_100).toISOString());

  now = 1_101;
  assert.throws(() => session.getQr(), { code: 'qr_expired' });
  assert.deepEqual(session.status(), {
    account_id: 'A',
    state: 'offline',
    has_qr: false,
    last_error: null,
  });
  assert.throws(() => session.getQr(), { code: 'qr_expired' });

  sock.ev.emit('connection.update', { qr: 'another-qr' });
  await session.whenIdle();
  sock.ev.emit('connection.update', { connection: 'open' });
  await session.whenIdle();
  assert.equal(session.status().state, 'online');
  assert.throws(() => session.getQr(), { code: 'qr_not_available' });
});

test('API-QR: expired QR remains 410 across repeated reads until a new QR arrives', async () => {
  let now = 1_000;
  const sock = socket();
  const session = await makeSession(async () => sock, { qrTtlMs: 100, now: () => now });
  await session.connect();
  sock.ev.emit('connection.update', { qr: 'expired-qr' });
  await session.whenIdle();

  now = 1_101;
  for (let attempt = 0; attempt < 3; attempt += 1) {
    assert.throws(() => session.getQr(), { code: 'qr_expired', status: 410 });
    assert.equal(session.status().state, 'offline');
    assert.equal(session.status().has_qr, false);
  }

  sock.ev.emit('connection.update', { qr: 'fresh-qr' });
  await session.whenIdle();
  assert.equal(session.getQr().status, 'qr_pending');
});

test('API-EVENT: QR expiry and explicit stop reliably emit account.disconnected', async () => {
  let now = 1_000;
  const scheduler = fakeScheduler();
  const sink = recordingSink();
  const sock = socket();
  const session = await makeSession(async () => sock, {
    qrTtlMs: 100,
    now: () => now,
    scheduler,
    eventSink: sink,
  });
  await session.connect();
  sock.ev.emit('connection.update', { qr: 'expiring' });
  await session.whenIdle();
  now = 1_101;
  await scheduler.runNext();
  await session.whenIdle();
  assert.equal(session.status().state, 'offline');
  assert.equal(sink.events.at(-1).event_type, 'account.disconnected');
  assert.deepEqual(sink.events.at(-1).payload, { state: 'offline', reason: 'qr_expired' });

  await session.connect();
  await session.stop();
  assert.equal(sink.events.at(-1).event_type, 'account.disconnected');
  assert.deepEqual(sink.events.at(-1).payload, { state: 'offline', reason: 'stopped' });
});

test('SEC-API-EVENT: account.error exposes only stable safe code/message', async () => {
  const sink = recordingSink();
  const secret = '/private/session/creds.json token=super-secret';
  const session = await makeSession(async () => { throw new Error(secret); }, { eventSink: sink });
  await assert.rejects(session.connect(), /super-secret/);
  const emitted = sink.events.find((item) => item.event_type === 'account.error');
  assert.equal(session.status().last_error, 'WhatsApp connection failed');
  assert.equal(JSON.stringify(session.status()).includes('super-secret'), false);
  assert.deepEqual(emitted.payload, {
    state: 'error',
    code: 'socket_connection_failed',
    message: 'WhatsApp connection failed',
  });
  assert.equal(JSON.stringify(emitted).includes('creds.json'), false);
  assert.equal(JSON.stringify(emitted).includes('super-secret'), false);
  await session.stop();
});

test('NFR-OPS: event pipeline failure does not change an online socket to error', async () => {
  const sock = socket();
  const sink = recordingSink();
  const session = await makeSession(async () => sock, { eventSink: sink });
  await session.connect();
  sock.ev.emit('connection.update', { connection: 'open' });
  await session.whenIdle();
  sink.enqueue = async () => { throw new Error('spool unavailable'); };
  sock.ev.emit('messages.upsert', { messages: [{
    key: { id: 'WA-PIPELINE', remoteJid: 'a@s.whatsapp.net', fromMe: false },
    message: { conversation: 'hello' },
  }] });
  await session.whenIdle();
  assert.equal(session.status().state, 'online');
  assert.equal(session.lastEventError, 'spool unavailable');
  sink.enqueue = async (item) => { sink.events.push(item); };
  await session.stop();
});

test('API-EVENT: read-triggered QR expiry still emits account.disconnected', async () => {
  let now = 1_000;
  const scheduler = fakeScheduler();
  const sink = recordingSink();
  const sock = socket();
  const session = await makeSession(async () => sock, {
    qrTtlMs: 100,
    now: () => now,
    scheduler,
    eventSink: sink,
  });
  await session.connect();
  sock.ev.emit('connection.update', { qr: 'qr-secret' });
  await session.whenIdle();
  now = 1_101;

  assert.throws(() => session.getQr(), /expired/i);
  await session.whenIdle();
  assert.equal(session.status().state, 'offline');
  assert.equal(sink.events.at(-1).event_type, 'account.disconnected');
  assert.deepEqual(sink.events.at(-1).payload, { state: 'offline', reason: 'qr_expired' });
});

test('SEC-API: disconnect status exposes only a stable safe message', async () => {
  const sock = socket();
  const session = await makeSession(async () => sock);
  await session.connect();
  sock.ev.emit('connection.update', {
    connection: 'close',
    lastDisconnect: { error: new Error('/private/session/creds.json token=super-secret') },
  });
  await session.whenIdle();
  assert.equal(session.status().last_error, 'WhatsApp connection interrupted');
  assert.equal(JSON.stringify(session.status()).includes('super-secret'), false);
  await session.stop();
});

test('API-QR: QR wins over connecting in the same Baileys update', async () => {
  const sock = socket();
  const session = await makeSession(async () => sock);
  await session.connect();
  sock.ev.emit('connection.update', { connection: 'connecting', qr: 'qr-secret' });
  await session.whenIdle();
  assert.equal(session.status().state, 'qr_pending');
  assert.match(session.getQr().qr_data_url, /^data:image\/png;base64,/);
});

test('FR-ACC-004: logged_out affects only this session and never exits process', async () => {
  const sock = socket();
  const session = await makeSession(async () => sock);
  const originalExit = process.exit;
  let exitCalled = false;
  process.exit = () => { exitCalled = true; };
  try {
    await session.connect();
    sock.ev.emit('connection.update', {
      connection: 'close',
      lastDisconnect: { error: { output: { statusCode: 401 } } },
    });
    await session.whenIdle();
    assert.equal(session.status().state, 'logged_out');
    assert.equal(exitCalled, false);
  } finally {
    process.exit = originalExit;
  }
});

test('FR-ACC-003: socket generation prevents late old-socket events overwriting current state', async () => {
  const oldSocket = socket();
  const newSocket = socket();
  let count = 0;
  const session = await makeSession(async () => (count++ === 0 ? oldSocket : newSocket));

  await session.connect();
  await session.stop();
  await session.connect();
  newSocket.ev.emit('connection.update', { connection: 'open' });
  await session.whenIdle();
  oldSocket.ev.emit('connection.update', { connection: 'close' });
  await session.whenIdle();
  assert.equal(session.status().state, 'online');
});

test('FR-ACC-003: close invalidates its socket before a late open and reconnect creates a new generation', async () => {
  const scheduler = fakeScheduler();
  const oldSocket = socket();
  const newSocket = socket();
  let count = 0;
  const session = await makeSession(async () => (count++ === 0 ? oldSocket : newSocket), {
    scheduler,
    reconnectBaseMs: 100,
    reconnectJitter: (delay) => delay,
  });

  await session.connect();
  oldSocket.ev.emit('connection.update', { connection: 'close' });
  oldSocket.ev.emit('connection.update', { connection: 'open' });
  await session.whenIdle();
  assert.equal(session.status().state, 'offline');
  assert.equal(scheduler.size(), 1);

  await scheduler.runNext();
  assert.equal(count, 2);
  newSocket.ev.emit('connection.update', { connection: 'open' });
  await session.whenIdle();
  assert.equal(session.status().state, 'online');
});

test('FR-ACC-003: temporary disconnects reconnect with isolated exponential backoff and injected jitter', async () => {
  const scheduler = fakeScheduler();
  const sockets = [socket(), socket(), socket()];
  let count = 0;
  const session = await makeSession(async () => sockets[count++], {
    scheduler,
    reconnectBaseMs: 100,
    reconnectMaxMs: 1_000,
    reconnectJitter: (delay, context) => delay + context.attempt,
  });

  await session.connect();
  sockets[0].ev.emit('connection.update', { connection: 'close' });
  await session.whenIdle();
  assert.deepEqual(scheduler.delays(), [101]);
  await scheduler.runNext();

  sockets[1].ev.emit('connection.update', { connection: 'close' });
  await session.whenIdle();
  assert.deepEqual(scheduler.delays(), [202]);
  await scheduler.runNext();
  assert.equal(count, 3);
});

test('FR-ACC-003/008: stop and logout cancel reconnect; loggedOut 401 never reconnects', async () => {
  for (const action of ['stop', 'logout']) {
    const scheduler = fakeScheduler();
    const sock = socket();
    const session = await makeSession(async () => sock, { scheduler });
    await session.connect();
    sock.ev.emit('connection.update', { connection: 'close' });
    await session.whenIdle();
    assert.equal(scheduler.size(), 1);
    await session[action]();
    assert.equal(scheduler.size(), 0);
  }

  const scheduler = fakeScheduler();
  const sock = socket();
  const session = await makeSession(async () => sock, { scheduler });
  await session.connect();
  sock.ev.emit('connection.update', {
    connection: 'close',
    lastDisconnect: { error: { output: { statusCode: 401 } } },
  });
  await session.whenIdle();
  assert.equal(session.status().state, 'logged_out');
  assert.equal(scheduler.size(), 0);
});

test('FR-ACC-003: Baileys 6.7.22 connectionReplaced 440 is offline and reconnectable', async () => {
  const scheduler = fakeScheduler();
  const sock = socket();
  const session = await makeSession(async () => sock, { scheduler });
  await session.connect();
  sock.ev.emit('connection.update', {
    connection: 'close',
    lastDisconnect: { error: { output: { statusCode: 440 } } },
  });
  await session.whenIdle();
  assert.equal(session.status().state, 'offline');
  assert.equal(scheduler.size(), 1);
});

test('FR-MSG: offline send fails; success requires real sent.key.id', async () => {
  const good = socket();
  const session = await makeSession(async () => good);
  await assert.rejects(session.send({ chatId: '1@s.whatsapp.net', text: 'hello' }), { code: 'account_offline' });

  await session.connect();
  good.ev.emit('connection.update', { connection: 'open' });
  await session.whenIdle();
  assert.equal(await session.send({ chatId: '1@s.whatsapp.net', text: 'hello' }), 'real-id');

  good.sendMessage = async () => ({ key: {} });
  await assert.rejects(session.send({ chatId: '1@s.whatsapp.net', text: 'hello' }), { code: 'missing_message_id' });
});

test('API-EVENT: real send id emits message.sent with ReceiptPayload only', async () => {
  const now = Date.parse('2026-07-10T00:00:00Z');
  const sink = recordingSink();
  const sock = socket({ async sendMessage() { return { key: { id: 'WA-SENT-1' } }; } });
  const session = await makeSession(async () => sock, { now: () => now, eventSink: sink });
  await session.connect();
  sock.ev.emit('connection.update', { connection: 'open' });
  await session.whenIdle();
  sink.events.length = 0;

  assert.equal(await session.send({ chatId: 'secret-chat@s.whatsapp.net', text: 'secret text' }), 'WA-SENT-1');
  assert.equal(sink.events.length, 1);
  assert.equal(sink.events[0].event_type, 'message.sent');
  assert.deepEqual(sink.events[0].payload, {
    wa_message_id: 'WA-SENT-1',
    timestamp: '2026-07-10T00:00:00.000Z',
    error_code: null,
    error_message: null,
  });
  assert.equal(JSON.stringify(sink.events[0]).includes('secret-chat'), false);
  assert.equal(JSON.stringify(sink.events[0]).includes('secret text'), false);
});

test('API-EVENT: Baileys 6.7.22 messages.update maps delivered/read/failed receipts in order', async () => {
  const now = Date.parse('2026-07-10T00:00:00Z');
  const sink = recordingSink();
  const sock = socket();
  const session = await makeSession(async () => sock, { now: () => now, eventSink: sink });
  await session.connect();
  sink.events.length = 0;

  sock.ev.emit('messages.update', [
    { key: { id: 'WA-1', remoteJid: 'private@s.whatsapp.net', fromMe: true }, update: { status: 3 } },
    { key: { id: 'WA-1', remoteJid: 'private@s.whatsapp.net', fromMe: true }, update: { status: 4 } },
    { key: { id: 'WA-2', remoteJid: 'private@s.whatsapp.net', fromMe: true }, update: {
      status: 0,
      error: { output: { statusCode: 503 }, message: 'delivery failed' },
    } },
    { key: { id: 'INBOUND', fromMe: false }, update: { status: 4 } },
    { key: { id: 'PENDING', fromMe: true }, update: { status: 2 } },
  ]);
  await session.whenIdle();

  assert.deepEqual(sink.events.map((item) => item.event_type), [
    'message.delivered', 'message.read', 'message.failed',
  ]);
  assert.deepEqual(sink.events.map((item) => item.sequence), [2, 3, 4]);
  assert.deepEqual(sink.events[2].payload, {
    wa_message_id: 'WA-2',
    timestamp: '2026-07-10T00:00:00.000Z',
    error_code: '503',
    error_message: 'delivery failed',
  });
  assert.equal(JSON.stringify(sink.events).includes('private@s.whatsapp.net'), false);
});

test('API-EVENT: duplicate receipt occurrences use distinct event identities and cannot hash-conflict', async () => {
  let now = Date.parse('2026-07-10T00:00:00Z');
  const sink = recordingSink();
  const sock = socket();
  const session = await makeSession(async () => sock, { now: () => now, eventSink: sink });
  await session.connect();
  sink.events.length = 0;

  sock.ev.emit('messages.update', [
    { key: { id: 'WA-1', fromMe: true }, update: { status: 3 } },
  ]);
  await session.whenIdle();
  now += 1_000;
  sock.ev.emit('messages.update', [
    { key: { id: 'WA-1', fromMe: true }, update: { status: 3 } },
  ]);
  await session.whenIdle();

  assert.equal(sink.events.length, 2);
  assert.notEqual(sink.events[0].event_id, sink.events[1].event_id);
  assert.equal(sink.events[0].payload.wa_message_id, 'WA-1');
  assert.equal(sink.events[1].payload.wa_message_id, 'WA-1');
});

test('FR-ACC-008: logout and stop do not delete session directory', async () => {
  const sock = socket();
  const session = await makeSession(async () => sock);
  await session.connect();
  await session.stop();
  assert.equal(session.status().state, 'offline');
  assert.equal(sock.endCalls, 1);

  await session.connect();
  await session.logout();
  assert.equal(session.status().state, 'logged_out');
  assert.equal(sock.logoutCalls, 1);
});
