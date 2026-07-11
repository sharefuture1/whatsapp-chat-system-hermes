import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { mkdtemp, mkdir, stat, writeFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';

import { AccountManager } from '../src/account-manager.js';

function roots(runtime) {
  return {
    sessionRoot: path.join(runtime, 'sessions'),
    spoolRoot: path.join(runtime, 'spool'),
    mediaRoot: path.join(runtime, 'media'),
  };
}

function fakeSocket(id = 'socket') {
  const ev = new EventEmitter();
  return {
    id,
    ev,
    endCalls: 0,
    logoutCalls: 0,
    async sendMessage() { return { key: { id: `${id}-message` } }; },
    async sendPresenceUpdate() {},
    end() { this.endCalls += 1; },
    async logout() { this.logoutCalls += 1; },
  };
}

function fakeScheduler() {
  const tasks = new Map();
  let id = 0;
  return {
    setTimeout(callback, delay) {
      tasks.set(++id, { callback, delay });
      return id;
    },
    clearTimeout(timerId) { tasks.delete(timerId); },
    size() { return tasks.size; },
  };
}

test('FR-ACC-003: concurrent connect for one account creates exactly one socket', async () => {
  const runtime = await mkdtemp(path.join(os.tmpdir(), 'bridge-manager-'));
  let calls = 0;
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  const manager = new AccountManager({
    ...roots(runtime),
    socketFactory: async () => {
      calls += 1;
      await gate;
      return fakeSocket();
    },
  });
  await manager.initialize();
  await manager.createAccount({ account_id: 'account-A', session_ref: 'account:account-A' });

  const first = manager.connect('account-A');
  const second = manager.connect('account-A');
  release();
  await Promise.all([first, second]);

  assert.equal(calls, 1);
  assert.equal(manager.get('account-A').socket.id, 'socket');
});

test('FR-CON-012: listStatuses returns safe manager status only', async () => {
  const runtime = await mkdtemp(path.join(os.tmpdir(), 'bridge-list-status-'));
  const manager = new AccountManager({ ...roots(runtime), socketFactory: async () => fakeSocket() });
  await manager.initialize();
  manager.createAccount({ account_id: 'A', session_ref: 'account:A' });

  assert.deepEqual(manager.listStatuses(), [
    { account_id: 'A', state: 'new', has_qr: false, last_error: null },
  ]);
  assert.equal(JSON.stringify(manager.listStatuses()).includes('session'), false);
  assert.equal(JSON.stringify(manager.listStatuses()).includes(runtime), false);
});

test('FR-ACC-003/004: A and B use isolated directories and sockets', async () => {
  const runtime = await mkdtemp(path.join(os.tmpdir(), 'bridge-isolation-'));
  const sockets = new Map();
  const manager = new AccountManager({
    ...roots(runtime),
    socketFactory: async ({ accountId }) => {
      const socket = fakeSocket(accountId);
      sockets.set(accountId, socket);
      return socket;
    },
  });
  await manager.initialize();
  const a = manager.createAccount({ account_id: 'A', session_ref: 'account:A' });
  const b = manager.createAccount({ account_id: 'B', session_ref: 'account:B' });
  await Promise.all([manager.connect('A'), manager.connect('B')]);

  assert.notEqual(a.sessionDir, b.sessionDir);
  assert.notEqual(a.spoolDir, b.spoolDir);
  assert.notEqual(a.mediaDir, b.mediaDir);
  assert.notEqual(a.socket, b.socket);
  for (const directory of [a.sessionDir, b.sessionDir, a.spoolDir, b.spoolDir, a.mediaDir, b.mediaDir]) {
    assert.equal((await stat(directory)).mode & 0o777, 0o700);
  }
});

test('SEC-005: account_id and session_ref path traversal are rejected', async () => {
  const runtime = await mkdtemp(path.join(os.tmpdir(), 'bridge-traversal-'));
  const manager = new AccountManager({ ...roots(runtime), socketFactory: async () => fakeSocket() });
  await manager.initialize();

  for (const accountId of ['../escape', '/tmp/escape', 'A/B', '.', '..', 'A%2fB']) {
    assert.throws(
      () => manager.createAccount({ account_id: accountId, session_ref: 'account:safe' }),
      { code: 'invalid_account_id' },
    );
  }
  for (const sessionRef of ['../escape', '/tmp/escape', 'account/A', '.', '..', 'account%2fA']) {
    assert.throws(
      () => manager.createAccount({ account_id: 'safe', session_ref: sessionRef }),
      { code: 'invalid_session_ref' },
    );
  }
});

test('FR-ACC-008: stop preserves session; only delete_session removes it', async () => {
  const runtime = await mkdtemp(path.join(os.tmpdir(), 'bridge-delete-'));
  const manager = new AccountManager({ ...roots(runtime), socketFactory: async () => fakeSocket() });
  await manager.initialize();
  const session = manager.createAccount({ account_id: 'A', session_ref: 'account:A' });
  await manager.connect('A');
  const marker = path.join(session.sessionDir, 'creds.json');
  await writeFile(marker, '{}');

  await manager.stop('A');
  assert.equal((await stat(marker)).isFile(), true);
  await manager.delete('A', { deleteSession: false });
  assert.equal((await stat(marker)).isFile(), true);

  manager.createAccount({ account_id: 'A', session_ref: 'account:A' });
  await manager.delete('A', { deleteSession: true });
  await assert.rejects(stat(marker), { code: 'ENOENT' });
});

test('FR-ACC-008: delete cancels a pending account reconnect timer', async () => {
  const runtime = await mkdtemp(path.join(os.tmpdir(), 'bridge-delete-reconnect-'));
  const scheduler = fakeScheduler();
  const sock = fakeSocket();
  const manager = new AccountManager({
    ...roots(runtime),
    socketFactory: async () => sock,
    scheduler,
  });
  await manager.initialize();
  manager.createAccount({ account_id: 'A', session_ref: 'account:A' });
  await manager.connect('A');
  sock.ev.emit('connection.update', { connection: 'close' });
  await manager.get('A').whenIdle();
  assert.equal(scheduler.size(), 1);
  await manager.delete('A', { deleteSession: false });
  assert.equal(scheduler.size(), 0);
});

test('API media contract: only account-scoped media_ref resolves inside account media root', async () => {
  const runtime = await mkdtemp(path.join(os.tmpdir(), 'bridge-media-'));
  const manager = new AccountManager({ ...roots(runtime), socketFactory: async () => fakeSocket() });
  await manager.initialize();
  const account = manager.createAccount({ account_id: 'A', session_ref: 'account:A' });
  await mkdir(account.mediaDir, { recursive: true });

  assert.equal(manager.resolveMedia('A', 'image-123'), path.join(account.mediaDir, 'image-123'));
  for (const mediaRef of ['/etc/passwd', '../secret', 'folder/file', '.', '..', 'x%2fy']) {
    assert.throws(() => manager.resolveMedia('A', mediaRef), { code: 'invalid_media_ref' });
  }
});

test('FR-ACC-003/008: create and connect during delete cannot succeed then be deleted', async () => {
  const runtime = await mkdtemp(path.join(os.tmpdir(), 'bridge-delete-race-'));
  let releaseStop;
  const stopGate = new Promise((resolve) => { releaseStop = resolve; });
  const manager = new AccountManager({ ...roots(runtime), socketFactory: async () => fakeSocket() });
  await manager.initialize();
  const original = manager.createAccount({ account_id: 'A', session_ref: 'account:A' });
  original.stop = async () => {
    await stopGate;
    return original.status();
  };

  const deleting = manager.delete('A', { deleteSession: false });
  const creating = manager.createAccount({ account_id: 'A', session_ref: 'account:A' });
  const connecting = manager.connect('A');
  releaseStop();
  await deleting;

  const replacement = await creating;
  await connecting;
  assert.notEqual(replacement, original);
  assert.equal(manager.get('A'), replacement);
  assert.equal(replacement.state, 'connecting');
});

test('NFR-OPS-002: readiness follows initialization and closeAll stops every account', async () => {
  const runtime = await mkdtemp(path.join(os.tmpdir(), 'bridge-close-all-'));
  const sockets = [];
  const manager = new AccountManager({
    ...roots(runtime),
    socketFactory: async () => {
      const sock = fakeSocket();
      sockets.push(sock);
      return sock;
    },
  });
  assert.equal(manager.isReady(), false);
  await manager.initialize();
  assert.equal(manager.isReady(), true);
  manager.createAccount({ account_id: 'A', session_ref: 'account:A' });
  manager.createAccount({ account_id: 'B', session_ref: 'account:B' });
  await Promise.all([manager.connect('A'), manager.connect('B')]);

  await manager.closeAll();
  assert.equal(manager.isReady(), false);
  assert.deepEqual(sockets.map((sock) => sock.endCalls), [1, 1]);
});
