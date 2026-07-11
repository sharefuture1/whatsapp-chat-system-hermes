import path from 'node:path';
import { chmod, mkdir, rm } from 'node:fs/promises';

import { AccountSession, BridgeDomainError } from './account-session.js';

const SAFE_ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;
const SAFE_MEDIA_REF = /^[A-Za-z0-9][A-Za-z0-9._-]{0,255}$/;

function validateOpaqueId(value, code, label, pattern = SAFE_ID) {
  if (typeof value !== 'string' || !pattern.test(value) || value === '.' || value === '..' || value.includes('%')) {
    throw new BridgeDomainError(code, `Invalid ${label}`, { status: 400 });
  }
  return value;
}

function childPath(root, leaf, code) {
  const resolvedRoot = path.resolve(root);
  const target = path.resolve(resolvedRoot, leaf);
  if (path.dirname(target) !== resolvedRoot) {
    throw new BridgeDomainError(code, 'Resolved path escapes configured root', { status: 400 });
  }
  return target;
}

async function secureRoot(root) {
  await mkdir(root, { recursive: true, mode: 0o700 });
  await chmod(root, 0o700);
}

export class AccountManager {
  constructor({
    sessionRoot,
    spoolRoot,
    mediaRoot,
    socketFactory,
    qrTtlMs = 60_000,
    now = Date.now,
    scheduler,
    reconnectBaseMs,
    reconnectMaxMs,
    reconnectJitter,
    eventSinkFactory,
  }) {
    if (typeof socketFactory !== 'function') throw new TypeError('socketFactory is required');
    this.sessionRoot = path.resolve(sessionRoot);
    this.spoolRoot = path.resolve(spoolRoot);
    this.mediaRoot = path.resolve(mediaRoot);
    this.socketFactory = socketFactory;
    this.qrTtlMs = qrTtlMs;
    this.now = now;
    this.scheduler = scheduler;
    this.reconnectBaseMs = reconnectBaseMs;
    this.reconnectMaxMs = reconnectMaxMs;
    this.reconnectJitter = reconnectJitter;
    this.eventSinkFactory = eventSinkFactory;
    this.sessions = new Map();
    this.lifecycle = new Map();
    this.ready = false;
  }

  async initialize() {
    await Promise.all([this.sessionRoot, this.spoolRoot, this.mediaRoot].map(secureRoot));
    this.ready = true;
  }

  isReady() {
    return this.ready;
  }

  createAccount({ account_id: accountId, session_ref: sessionRef }) {
    validateOpaqueId(accountId, 'invalid_account_id', 'account_id');
    validateOpaqueId(sessionRef, 'invalid_session_ref', 'session_ref');
    const pending = this.lifecycle.get(accountId);
    if (pending) {
      return pending.then(() => this.createAccount({ account_id: accountId, session_ref: sessionRef }));
    }
    const existing = this.sessions.get(accountId);
    if (existing) {
      if (existing.sessionRef !== sessionRef) {
        throw new BridgeDomainError('account_conflict', 'Account already exists with another session_ref', {
          status: 409,
        });
      }
      return existing;
    }

    const session = new AccountSession({
      accountId,
      sessionRef,
      sessionDir: childPath(this.sessionRoot, accountId, 'invalid_account_id'),
      spoolDir: childPath(this.spoolRoot, accountId, 'invalid_account_id'),
      mediaDir: childPath(this.mediaRoot, accountId, 'invalid_account_id'),
      socketFactory: this.socketFactory,
      qrTtlMs: this.qrTtlMs,
      now: this.now,
      scheduler: this.scheduler,
      reconnectBaseMs: this.reconnectBaseMs,
      reconnectMaxMs: this.reconnectMaxMs,
      reconnectJitter: this.reconnectJitter,
      eventSink: this.eventSinkFactory?.({ accountId, spoolDir: childPath(this.spoolRoot, accountId, 'invalid_account_id') }),
    });
    this.sessions.set(accountId, session);
    return session;
  }

  get(accountId) {
    validateOpaqueId(accountId, 'invalid_account_id', 'account_id');
    const session = this.sessions.get(accountId);
    if (!session) {
      throw new BridgeDomainError('account_not_found', 'Account does not exist', { status: 404 });
    }
    return session;
  }

  async connect(accountId) {
    const pending = this.lifecycle.get(accountId);
    if (pending) return pending.then(() => this.connect(accountId));
    return this.get(accountId).connect();
  }

  status(accountId) {
    return this.get(accountId).status();
  }

  listStatuses() {
    return [...this.sessions.values()].map((session) => session.status());
  }

  qr(accountId) {
    return this.get(accountId).getQr();
  }

  async stop(accountId) {
    return this.get(accountId).stop();
  }

  async logout(accountId) {
    return this.get(accountId).logout();
  }

  async send(accountId, payload) {
    return this.get(accountId).send(payload);
  }

  async typing(accountId, payload) {
    return this.get(accountId).typing(payload);
  }

  resolveMedia(accountId, mediaRef) {
    const session = this.get(accountId);
    validateOpaqueId(mediaRef, 'invalid_media_ref', 'media_ref', SAFE_MEDIA_REF);
    return childPath(session.mediaDir, mediaRef, 'invalid_media_ref');
  }

  async delete(accountId, { deleteSession = false } = {}) {
    validateOpaqueId(accountId, 'invalid_account_id', 'account_id');
    const previous = this.lifecycle.get(accountId) ?? Promise.resolve();
    let operation;
    operation = previous.then(async () => {
      const session = this.get(accountId);
      await session.close();
      this.sessions.delete(accountId);
      if (deleteSession) {
        await rm(session.sessionDir, { recursive: true, force: true });
      }
      return { success: true, account_id: accountId, session_deleted: Boolean(deleteSession) };
    }).finally(() => {
      if (this.lifecycle.get(accountId) === operation) this.lifecycle.delete(accountId);
    });
    this.lifecycle.set(accountId, operation);
    return operation;
  }

  async closeAll() {
    this.ready = false;
    await Promise.allSettled([...this.lifecycle.values()]);
    await Promise.allSettled([...this.sessions.values()].map((session) => session.close()));
  }
}
