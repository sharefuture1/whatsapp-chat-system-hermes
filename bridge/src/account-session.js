import { createHash, randomUUID } from 'node:crypto';
import { chmod, mkdir } from 'node:fs/promises';
import { DisconnectReason } from '@whiskeysockets/baileys';
import QRCode from 'qrcode';

import { normalizeChat, normalizeContact, occurrenceChunkIdentity } from './sync-normalizer.js';

export const ACCOUNT_STATES = Object.freeze([
  'new',
  'qr_pending',
  'connecting',
  'online',
  'offline',
  'error',
  'logged_out',
]);

export class BridgeDomainError extends Error {
  constructor(code, message, { status = 400, retryable = false } = {}) {
    super(message);
    this.name = 'BridgeDomainError';
    this.code = code;
    this.status = status;
    this.retryable = retryable;
  }
}

function disconnectStatusCode(update) {
  return update?.lastDisconnect?.error?.output?.statusCode
    ?? update?.lastDisconnect?.error?.statusCode
    ?? update?.lastDisconnect?.error?.data?.statusCode;
}

function isLoggedOut(update) {
  return disconnectStatusCode(update) === 401;
}

const defaultScheduler = Object.freeze({
  setTimeout: (callback, delay) => setTimeout(callback, delay),
  clearTimeout: (timer) => clearTimeout(timer),
});

function defaultReconnectJitter(delay) {
  return Math.round(delay * (0.8 + Math.random() * 0.4));
}

function normalizeMessage(message, now) {
  const key = message?.key ?? {};
  const content = message?.message ?? {};
  const [rawType, rawPayload] = Object.entries(content)
    .find(([, value]) => value !== null && value !== undefined) ?? ['unknown', null];
  const typeMap = {
    conversation: 'text',
    extendedTextMessage: 'text',
    imageMessage: 'image',
    audioMessage: 'audio',
    videoMessage: 'video',
    documentMessage: 'document',
  };
  const messageType = typeMap[rawType] ?? 'system';
  const remoteJid = key.remoteJid;
  const allowedJid = typeof remoteJid === 'string'
    && ['@s.whatsapp.net', '@lid', '@g.us'].some(suffix => remoteJid.endsWith(suffix));
  if (messageType === 'system' || !allowedJid) return null;
  const seconds = Number(message?.messageTimestamp);
  return {
    schema_version: 1,
    wa_message_id: key.id,
    remote_jid: remoteJid,
    sender_jid: key.fromMe ? null : (key.participant ?? remoteJid),
    participant_jid: key.participant ?? null,
    from_me: Boolean(key.fromMe),
    conversation_type: String(key.remoteJid ?? '').endsWith('@g.us') ? 'group' : 'dm',
    message_type: messageType,
    timestamp: new Date(Number.isFinite(seconds) && seconds > 0 ? seconds * 1_000 : now()).toISOString(),
    text: rawType === 'conversation'
      ? String(rawPayload ?? '')
      : String(rawPayload?.text ?? rawPayload?.caption ?? ''),
    push_name: message?.pushName ?? null,
    quoted_wa_message_id: rawPayload?.contextInfo?.stanzaId ?? null,
    media: messageType === 'text' || messageType === 'system' ? null : {
      mime_type: rawPayload?.mimetype ?? null,
      file_name: rawPayload?.fileName ?? null,
    },
  };
}

// Baileys 6.7.22 WAProto.WebMessageInfo.Status:
// ERROR=0, PENDING=1, SERVER_ACK=2, DELIVERY_ACK=3, READ=4, PLAYED=5.
function normalizeReceipt(update, now) {
  const key = update?.key ?? {};
  if (key.fromMe !== true || typeof key.id !== 'string' || key.id.length === 0) return null;
  const status = Number(update?.update?.status);
  const eventType = { 0: 'message.failed', 3: 'message.delivered', 4: 'message.read', 5: 'message.read' }[status];
  if (!eventType) return null;
  const error = update?.update?.error;
  const errorCode = error?.output?.statusCode ?? error?.statusCode ?? error?.data?.statusCode;
  return {
    eventType,
    payload: {
      wa_message_id: key.id,
      timestamp: new Date(now()).toISOString(),
      error_code: eventType === 'message.failed' && errorCode !== undefined ? String(errorCode) : null,
      error_message: eventType === 'message.failed' ? String(error?.message ?? 'WhatsApp delivery failed') : null,
    },
  };
}

async function secureDirectory(directory) {
  await mkdir(directory, { recursive: true, mode: 0o700 });
  await chmod(directory, 0o700);
}

export class AccountSession {
  constructor({
    accountId,
    sessionRef,
    sessionDir,
    spoolDir,
    mediaDir,
    socketFactory,
    qrTtlMs = 60_000,
    now = Date.now,
    scheduler = defaultScheduler,
    reconnectBaseMs = 1_000,
    reconnectMaxMs = 30_000,
    reconnectJitter = defaultReconnectJitter,
    eventSink = null,
  }) {
    this.accountId = accountId;
    this.sessionRef = sessionRef;
    this.sessionDir = sessionDir;
    this.spoolDir = spoolDir;
    this.mediaDir = mediaDir;
    this.socketFactory = socketFactory;
    this.qrTtlMs = qrTtlMs;
    this.now = now;
    this.scheduler = scheduler;
    this.reconnectBaseMs = reconnectBaseMs;
    this.reconnectMaxMs = reconnectMaxMs;
    this.reconnectJitter = reconnectJitter;
    this.eventSink = eventSink;

    this.state = 'new';
    this.socket = null;
    this.connectPromise = null;
    this.generation = 0;
    this.qr = null;
    this.qrExpired = false;
    this.lastError = null;
    this.lastEventError = null;
    this.eventWork = Promise.resolve();
    this.reconnectTimer = null;
    this.reconnectAttempt = 0;
    this.autoReconnect = false;
    this.sinkStarted = false;
    this.qrExpiryTimer = null;
  }

  async initialize() {
    await Promise.all([this.sessionDir, this.spoolDir, this.mediaDir].map(secureDirectory));
    if (this.eventSink && !this.sinkStarted) {
      await this.eventSink.start();
      this.sinkStarted = true;
    }
  }

  status() {
    this.#expireQrIfNeeded();
    return {
      account_id: this.accountId,
      state: this.state,
      has_qr: Boolean(this.qr && this.qr.expiresAt > this.now()),
      last_error: this.lastError,
    };
  }

  async connect({ isReconnect = false } = {}) {
    if (this.state === 'online' && this.socket) return this.status();
    if (this.connectPromise) return this.connectPromise;

    if (!isReconnect) {
      this.autoReconnect = true;
      this.reconnectAttempt = 0;
      this.#cancelReconnect();
    }

    const generation = ++this.generation;
    this.state = 'connecting';
    this.lastError = null;
    this.lastEventError = null;
    this.qr = null;
    this.qrExpired = false;
    this.#cancelQrExpiry();

    const promise = (async () => {
      await this.initialize();
      await this.#emitEvent('account.connecting', { state: 'connecting' });
      const socket = await this.socketFactory({
        accountId: this.accountId,
        sessionRef: this.sessionRef,
        sessionDir: this.sessionDir,
        generation,
      });
      if (!socket || !socket.ev || typeof socket.ev.on !== 'function') {
        throw new BridgeDomainError('socket_factory_invalid', 'Socket factory returned an invalid socket', {
          status: 500,
          retryable: true,
        });
      }
      if (generation !== this.generation) {
        socket.end?.(new Error('stale socket generation'));
        return this.status();
      }
      this.socket = socket;
      socket.ev.on('connection.update', (update) => {
        this.eventWork = this.eventWork
          .then(() => this.#handleConnectionUpdate(generation, update))
          .catch((error) => {
            if (generation !== this.generation) return;
            this.#recordEventError(error);
          });
      });
      socket.ev.on('messages.upsert', (update) => {
        this.eventWork = this.eventWork
          .then(async () => {
            if (generation !== this.generation) return;
            for (const message of update?.messages ?? []) {
              const payload = normalizeMessage(message, this.now);
              if (!payload || typeof payload.wa_message_id !== 'string' || typeof payload.remote_jid !== 'string') continue;
              await this.#emitEvent('message.upsert', payload, `message:${payload.wa_message_id}`);
            }
          })
          .catch((error) => {
            if (generation !== this.generation) return;
            this.#recordEventError(error);
          });
      });
      socket.ev.on('messages.update', (updates) => {
        this.eventWork = this.eventWork
          .then(async () => {
            if (generation !== this.generation) return;
            for (const update of updates ?? []) {
              const receipt = normalizeReceipt(update, this.now);
              if (!receipt) continue;
              await this.#emitEvent(
                receipt.eventType,
                receipt.payload,
              );
            }
          })
          .catch((error) => {
            if (generation !== this.generation) return;
            this.#recordEventError(error);
          });
      });
      for (const [source, eventType, normalizer] of [
        ['contacts.upsert', 'contacts.upsert', normalizeContact],
        ['contacts.update', 'contacts.update', normalizeContact],
        ['chats.upsert', 'chats.upsert', normalizeChat],
        ['chats.update', 'chats.update', normalizeChat],
      ]) {
        socket.ev.on(source, (items) => this.#queueSyncBatch(
          generation, randomUUID(), eventType, items, normalizer, 200,
        ));
      }
      socket.ev.on('messaging-history.set', (history) => {
        const occurrenceId = randomUUID();
        this.#queueSyncBatch(generation, occurrenceId, 'contacts.upsert', history?.contacts, normalizeContact, 200, 5000);
        this.#queueSyncBatch(generation, occurrenceId, 'chats.upsert', history?.chats, normalizeChat, 200, 5000);
        this.#queueHistoryMessages(generation, occurrenceId, history?.messages);
      });
      return this.status();
    })();
    this.connectPromise = promise;

    try {
      return await promise;
    } catch (error) {
      if (generation === this.generation) {
        this.state = 'error';
        this.lastError = 'WhatsApp connection failed';
        this.socket = null;
        try {
          await this.#emitEvent('account.error', {
            state: 'error',
            code: 'socket_connection_failed',
            message: 'WhatsApp connection failed',
          });
        } catch {
          // The original connection failure remains authoritative; the event is already spooled if possible.
        }
        if (this.autoReconnect) this.#scheduleReconnect();
      }
      throw error;
    } finally {
      if (this.connectPromise === promise) this.connectPromise = null;
    }
  }

  async #handleConnectionUpdate(generation, update = {}) {
    if (generation !== this.generation) return;

    if (typeof update.qr === 'string' && update.qr.length > 0) {
      const generatedAt = this.now();
      const dataUrl = await QRCode.toDataURL(update.qr, {
        errorCorrectionLevel: 'M',
        margin: 2,
        width: 320,
      });
      if (generation !== this.generation) return;
      this.qr = {
        dataUrl,
        generatedAt,
        expiresAt: generatedAt + this.qrTtlMs,
      };
      this.qrExpired = false;
      this.state = 'qr_pending';
      this.#scheduleQrExpiry(generation, this.qr.expiresAt - generatedAt);
      await this.#emitEvent('account.qr', {
        state: 'qr_pending',
        expires_at: new Date(this.qr.expiresAt).toISOString(),
      });
    }

    if (update.connection === 'connecting' && !this.qr) {
      this.state = 'connecting';
      await this.#emitEvent('account.connecting', { state: 'connecting' });
    }
    if (update.connection === 'open') {
      this.state = 'online';
      this.qr = null;
      this.#cancelQrExpiry();
      this.lastError = null;
      this.reconnectAttempt = 0;
      this.#cancelReconnect();
      await this.#emitEvent('account.connected', { state: 'online' });
    }
    if (update.connection === 'close') {
      ++this.generation;
      this.qr = null;
      this.#cancelQrExpiry();
      this.socket = null;
      this.connectPromise = null;
      if (isLoggedOut(update)) {
        this.state = 'logged_out';
        this.autoReconnect = false;
        this.#cancelReconnect();
        await this.#emitEvent('account.logged_out', { state: 'logged_out' });
      } else {
        this.state = 'offline';
        this.lastError = 'WhatsApp connection interrupted';
        if (this.autoReconnect) this.#scheduleReconnect();
        await this.#emitEvent('account.disconnected', {
          state: 'offline',
          error_code: disconnectStatusCode(update) ?? null,
        });
      }
    }
  }

  #scheduleReconnect() {
    if (this.reconnectTimer !== null || !this.autoReconnect || this.state === 'logged_out') return;
    const attempt = ++this.reconnectAttempt;
    const exponentialDelay = Math.min(
      this.reconnectMaxMs,
      this.reconnectBaseMs * (2 ** (attempt - 1)),
    );
    const jitteredDelay = this.reconnectJitter(exponentialDelay, {
      accountId: this.accountId,
      attempt,
    });
    const delay = Math.max(0, Math.min(this.reconnectMaxMs, Number(jitteredDelay) || 0));
    this.reconnectTimer = this.scheduler.setTimeout(async () => {
      this.reconnectTimer = null;
      if (!this.autoReconnect || this.state === 'logged_out') return;
      try {
        await this.connect({ isReconnect: true });
      } catch {
        // connect() records the error and schedules the next bounded retry.
      }
    }, delay);
  }

  #cancelReconnect() {
    if (this.reconnectTimer === null) return;
    this.scheduler.clearTimeout(this.reconnectTimer);
    this.reconnectTimer = null;
  }

  #scheduleQrExpiry(generation, delay) {
    this.#cancelQrExpiry();
    this.qrExpiryTimer = this.scheduler.setTimeout(() => {
      this.qrExpiryTimer = null;
      this.eventWork = this.eventWork
        .then(async () => {
          if (generation !== this.generation || !this.qr || this.qr.expiresAt > this.now()) return;
          this.qr = null;
          this.qrExpired = true;
          if (this.state === 'qr_pending') {
            this.state = 'offline';
            await this.#emitEvent('account.disconnected', { state: 'offline', reason: 'qr_expired' });
          }
        })
        .catch((error) => this.#recordEventError(error));
    }, Math.max(0, delay));
  }

  #cancelQrExpiry() {
    if (this.qrExpiryTimer === null) return;
    this.scheduler.clearTimeout(this.qrExpiryTimer);
    this.qrExpiryTimer = null;
  }

  #recordEventError(error) {
    this.lastEventError = String(error?.message || error);
  }

  async whenIdle() {
    await this.eventWork;
  }

  #queueSyncBatch(generation, occurrenceId, eventType, rawItems, normalizer, size, maxItems = Infinity) {
    this.eventWork = this.eventWork.then(async () => {
      if (generation !== this.generation) return;
      let chunk = [];
      let chunkIndex = 0;
      let accepted = 0;
      for (const rawItem of rawItems ?? []) {
        if (accepted >= maxItems) break;
        const item = normalizer(rawItem);
        if (!item) continue;
        chunk.push(item);
        accepted += 1;
        if (chunk.length < size) continue;
        if (generation !== this.generation) return;
        await this.#emitEvent(eventType, { schema_version: 1, items: chunk },
          occurrenceChunkIdentity(occurrenceId, eventType, chunk, chunkIndex++));
        chunk = [];
      }
      if (chunk.length && generation === this.generation) await this.#emitEvent(
        eventType, { schema_version: 1, items: chunk },
        occurrenceChunkIdentity(occurrenceId, eventType, chunk, chunkIndex));
    }).catch((error) => {
      if (generation === this.generation) this.#recordEventError(error);
    });
  }

  #queueHistoryMessages(generation, occurrenceId, rawItems) {
    const cutoff = this.now() - (90 * 24 * 60 * 60 * 1000);
    this.eventWork = this.eventWork.then(async () => {
      const perConversation = new Map();
      let chunk = [];
      let chunkIndex = 0;
      let accepted = 0;
      for (const rawItem of rawItems ?? []) {
        if (accepted >= 2000 || generation !== this.generation) break;
        const seconds = Number(rawItem?.messageTimestamp);
        if (Number.isFinite(seconds) && seconds > 0 && seconds * 1000 < cutoff) continue;
        const item = normalizeMessage(rawItem, this.now);
        if (!item) continue;
        const count = perConversation.get(item.remote_jid) ?? 0;
        if (count >= 200) continue;
        perConversation.set(item.remote_jid, count + 1);
        chunk.push(item);
        accepted += 1;
        if (chunk.length < 100) continue;
        await this.#emitEvent('history.messages.upsert', { schema_version: 1, items: chunk },
          occurrenceChunkIdentity(occurrenceId, 'history.messages.upsert', chunk, chunkIndex++));
        chunk = [];
      }
      if (chunk.length && generation === this.generation) await this.#emitEvent(
        'history.messages.upsert', { schema_version: 1, items: chunk },
        occurrenceChunkIdentity(occurrenceId, 'history.messages.upsert', chunk, chunkIndex));
    }).catch((error) => {
      if (generation === this.generation) this.#recordEventError(error);
    });
  }

  async #emitEvent(eventType, payload, stableId = null) {
    if (!this.eventSink) return;
    const sequence = await this.eventSink.nextSequence();
    const identity = stableId ?? `${eventType}:${sequence}:${randomUUID()}`;
    await this.eventSink.enqueue({
      event_id: createHash('sha256').update(`${this.accountId}:${identity}`).digest('hex'),
      event_type: eventType,
      account_id: this.accountId,
      occurred_at: new Date(this.now()).toISOString(),
      sequence,
      payload,
    });
  }

  getQr() {
    this.#expireQrIfNeeded();
    if (this.qrExpired) {
      throw new BridgeDomainError('qr_expired', 'QR code has expired', { status: 410, retryable: true });
    }
    if (!this.qr) {
      throw new BridgeDomainError('qr_not_available', 'QR code is not available', { status: 409, retryable: true });
    }
    return {
      account_id: this.accountId,
      status: 'qr_pending',
      qr_data_url: this.qr.dataUrl,
      generated_at: new Date(this.qr.generatedAt).toISOString(),
      expires_at: new Date(this.qr.expiresAt).toISOString(),
    };
  }

  #expireQrIfNeeded() {
    if (!this.qr || this.qr.expiresAt > this.now()) return;
    this.#cancelQrExpiry();
    this.qr = null;
    this.qrExpired = true;
    if (this.state === 'qr_pending') {
      this.state = 'offline';
      this.eventWork = this.eventWork
        .then(() => this.#emitEvent('account.disconnected', { state: 'offline', reason: 'qr_expired' }))
        .catch((error) => this.#recordEventError(error));
    }
  }

  async stop() {
    this.autoReconnect = false;
    this.#cancelReconnect();
    this.reconnectAttempt = 0;
    ++this.generation;
    const socket = this.socket;
    this.socket = null;
    this.connectPromise = null;
    this.qr = null;
    this.state = 'offline';
    socket?.end?.(new Error('account stopped'));
    this.#cancelQrExpiry();
    await this.#emitEvent('account.disconnected', { state: 'offline', reason: 'stopped' });
    return this.status();
  }

  async logout() {
    this.autoReconnect = false;
    this.#cancelReconnect();
    this.reconnectAttempt = 0;
    ++this.generation;
    const socket = this.socket;
    this.socket = null;
    this.connectPromise = null;
    this.qr = null;
    this.#cancelQrExpiry();
    try {
      if (socket?.logout) await socket.logout();
      else socket?.end?.(new Error('account logged out'));
    } finally {
      this.state = 'logged_out';
    }
    return this.status();
  }

  async close() {
    await this.stop();
    if (this.eventSink && this.sinkStarted) {
      await this.eventSink.stop();
      this.sinkStarted = false;
    }
  }

  async send({ chatId, text }) {
    if (this.state !== 'online' || !this.socket) {
      throw new BridgeDomainError('account_offline', 'Account is not online', { status: 409, retryable: true });
    }
    const sent = await this.socket.sendMessage(chatId, { text });
    const messageId = sent?.key?.id;
    if (typeof messageId !== 'string' || !messageId.trim()) {
      throw new BridgeDomainError(
        'missing_message_id',
        'WhatsApp did not return a message ID',
        { status: 502, retryable: true },
      );
    }
    await this.#emitEvent('message.sent', {
      wa_message_id: messageId,
      timestamp: new Date(this.now()).toISOString(),
      error_code: null,
      error_message: null,
    }, `receipt:${messageId}:message.sent`);
    return messageId;
  }

  async typing({ chatId, typing }) {
    if (this.state !== 'online' || !this.socket) {
      throw new BridgeDomainError('account_offline', 'Account is not online', { status: 409, retryable: true });
    }
    await this.socket.sendPresenceUpdate(typing ? 'composing' : 'paused', chatId);
  }
}
