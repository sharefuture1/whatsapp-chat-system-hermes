import { createHash, randomUUID } from 'node:crypto';
import path from 'node:path';
import {
  chmod,
  mkdir,
  open,
  readFile,
  readdir,
  rename,
  rm,
} from 'node:fs/promises';

const SAFE_ACCOUNT_ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;

async function secureDirectory(directory) {
  await mkdir(directory, { recursive: true, mode: 0o700 });
  await chmod(directory, 0o700);
}

async function fsyncDirectory(directory) {
  const handle = await open(directory, 'r');
  try {
    await handle.sync();
  } finally {
    await handle.close();
  }
}

function validateAccountId(accountId) {
  if (
    typeof accountId !== 'string'
    || !SAFE_ACCOUNT_ID.test(accountId)
    || accountId === '.'
    || accountId === '..'
    || accountId.includes('%')
  ) {
    throw new TypeError('Invalid spool account_id');
  }
}

function validateEvent(event, accountId) {
  if (!event || typeof event !== 'object' || Array.isArray(event)) {
    throw new TypeError('Event must be an object');
  }
  if (event.account_id !== accountId) throw new TypeError('Event account_id does not match spool account');
  if (typeof event.event_id !== 'string' || event.event_id.length === 0) {
    throw new TypeError('Event event_id is required');
  }
  // Migration backfill may use sequence 0, but all live Bridge envelopes start at 1.
  if (!Number.isSafeInteger(event.sequence) || event.sequence < 1) {
    throw new TypeError('Realtime event sequence must be an integer >= 1');
  }
}

function canonicalize(value) {
  if (Array.isArray(value)) return value.map(canonicalize);
  if (value && typeof value === 'object') {
    return Object.fromEntries(
      Object.keys(value).sort().map((key) => [key, canonicalize(value[key])]),
    );
  }
  return value;
}

function canonicalEnvelope(event) {
  return JSON.stringify(canonicalize(event));
}

export class EventIdentityConflictError extends Error {
  constructor(eventId) {
    super(`event_identity_conflict: event_id ${eventId} already exists with different content`);
    this.name = 'EventIdentityConflictError';
    this.code = 'event_identity_conflict';
  }
}

function keyForEvent(eventId) {
  return `${createHash('sha256').update(eventId, 'utf8').digest('hex')}.json`;
}

function isQueueFile(name) {
  return /^[a-f0-9]{64}\.json$/.test(name) || name.endsWith('.json');
}

export class FileSpool {
  constructor({ root, accountId, now = Date.now }) {
    validateAccountId(accountId);
    if (typeof root !== 'string' || root.length === 0) throw new TypeError('Spool root is required');
    this.root = path.resolve(root);
    this.accountId = accountId;
    this.now = now;
    this.accountDir = path.resolve(this.root, accountId);
    if (path.dirname(this.accountDir) !== this.root) throw new TypeError('Spool path escapes configured root');
    this.pendingDir = path.join(this.accountDir, 'pending');
    this.inflightDir = path.join(this.accountDir, 'inflight');
    this.deadDir = path.join(this.accountDir, 'dead');
    this.sequencePath = path.join(this.accountDir, 'sequence');
    this.enqueueOrderPath = path.join(this.accountDir, 'enqueue-order');
    this.initialized = false;
    this.operation = Promise.resolve();
  }

  async initialize() {
    return this.#serial(async () => {
      await secureDirectory(this.root);
      await Promise.all([
        this.accountDir,
        this.pendingDir,
        this.inflightDir,
        this.deadDir,
      ].map(secureDirectory));
      await this.#recoverInflight();
      this.initialized = true;
    });
  }

  async nextSequence() {
    return this.#serial(async () => {
      await this.#ensureInitialized();
      let current = 0;
      try {
        current = Number((await readFile(this.sequencePath, 'utf8')).trim());
      } catch (error) {
        if (error.code !== 'ENOENT') throw error;
      }
      if (!Number.isSafeInteger(current) || current < 0) throw new Error('Corrupt spool sequence');
      const next = current + 1;
      await this.#atomicWrite(this.accountDir, 'sequence', next);
      return next;
    });
  }

  async append(event) {
    validateEvent(event, this.accountId);
    return this.#serial(async () => {
      await this.#ensureInitialized();
      const key = keyForEvent(event.event_id);
      const existing = await this.#findExisting(key);
      if (existing) {
        if (canonicalEnvelope(existing.record.event) !== canonicalEnvelope(event)) {
          throw new EventIdentityConflictError(event.event_id);
        }
        return { key, state: existing.state };
      }
      const enqueueOrder = await this.#nextCounter(this.enqueueOrderPath, 'enqueue-order');
      const record = {
        event,
        enqueue_order: enqueueOrder,
        attempt: 0,
        available_at: this.now(),
        last_error: null,
      };
      await this.#atomicWrite(this.pendingDir, key, record);
      return { key, state: 'pending' };
    });
  }

  async claim() {
    return this.#serial(async () => {
      await this.#ensureInitialized();
      const names = (await readdir(this.pendingDir)).filter(isQueueFile);
      const candidates = [];
      for (const key of names) {
        const pendingPath = path.join(this.pendingDir, key);
        let record;
        try {
          record = JSON.parse(await readFile(pendingPath, 'utf8'));
          this.#validateRecord(record);
        } catch {
          await this.#moveCorrupt(pendingPath, key);
          continue;
        }
        candidates.push({ key, pendingPath, record });
      }
      candidates.sort((left, right) => {
        const sequence = Number(left.record.event.sequence ?? 0) - Number(right.record.event.sequence ?? 0);
        if (sequence !== 0) return sequence;
        const enqueueOrder = Number(left.record.enqueue_order ?? Number.MAX_SAFE_INTEGER)
          - Number(right.record.enqueue_order ?? Number.MAX_SAFE_INTEGER);
        if (enqueueOrder !== 0) return enqueueOrder;
        return left.key.localeCompare(right.key);
      });
      for (const { key, pendingPath, record } of candidates) {
        if (Number(record.available_at ?? 0) > this.now()) return null;
        const inflightPath = path.join(this.inflightDir, key);
        try {
          await rename(pendingPath, inflightPath);
          await Promise.all([fsyncDirectory(this.pendingDir), fsyncDirectory(this.inflightDir)]);
        } catch (error) {
          if (error.code === 'ENOENT') continue;
          throw error;
        }
        return { key, ...record };
      }
      return null;
    });
  }

  async complete(claim) {
    return this.#serial(async () => {
      await this.#ensureInitialized();
      const key = this.#claimKey(claim);
      await rm(path.join(this.inflightDir, key), { force: true });
      await fsyncDirectory(this.inflightDir);
    });
  }

  async release(claim, { error = null, delayMs = 0 } = {}) {
    return this.#serial(async () => {
      await this.#ensureInitialized();
      const key = this.#claimKey(claim);
      const record = {
        event: claim.event,
        enqueue_order: claim.enqueue_order,
        attempt: Number(claim.attempt ?? 0) + 1,
        available_at: this.now() + Math.max(0, Number(delayMs) || 0),
        last_error: error === null ? null : String(error),
      };
      this.#validateRecord(record);
      await this.#atomicWrite(this.inflightDir, key, record);
      await rename(path.join(this.inflightDir, key), path.join(this.pendingDir, key));
      await Promise.all([fsyncDirectory(this.inflightDir), fsyncDirectory(this.pendingDir)]);
      return { key, ...record };
    });
  }

  async deadLetter(claim, { error = null } = {}) {
    return this.#serial(async () => {
      await this.#ensureInitialized();
      const key = this.#claimKey(claim);
      const record = {
        event: claim.event,
        enqueue_order: claim.enqueue_order,
        attempt: Number(claim.attempt ?? 0) + 1,
        available_at: null,
        last_error: error === null ? null : String(error),
        dead_at: this.now(),
      };
      await this.#atomicWrite(this.inflightDir, key, record);
      await rename(path.join(this.inflightDir, key), path.join(this.deadDir, key));
      await Promise.all([fsyncDirectory(this.inflightDir), fsyncDirectory(this.deadDir)]);
      return { key, ...record };
    });
  }

  async #recoverInflight() {
    const names = (await readdir(this.inflightDir)).filter(isQueueFile).sort();
    for (const key of names) {
      const source = path.join(this.inflightDir, key);
      try {
        const record = JSON.parse(await readFile(source, 'utf8'));
        this.#validateRecord(record);
      } catch {
        await this.#moveCorrupt(source, key);
        continue;
      }
      const pending = path.join(this.pendingDir, key);
      try {
        await rename(source, pending);
      } catch (error) {
        if (error.code !== 'EEXIST') throw error;
        await rm(source, { force: true });
      }
    }
    await Promise.all([fsyncDirectory(this.inflightDir), fsyncDirectory(this.pendingDir)]);
  }

  async #moveCorrupt(source, key) {
    let target = path.join(this.deadDir, key);
    try {
      await rename(source, target);
    } catch (error) {
      if (error.code !== 'EEXIST') throw error;
      target = path.join(this.deadDir, `${key}.${randomUUID()}.corrupt`);
      await rename(source, target);
    }
    await fsyncDirectory(this.deadDir);
  }

  async #findExisting(key) {
    for (const [state, directory] of [
      ['pending', this.pendingDir],
      ['inflight', this.inflightDir],
      ['dead', this.deadDir],
    ]) {
      try {
        const record = JSON.parse(await readFile(path.join(directory, key), 'utf8'));
        this.#validateRecord(record);
        return { state, record };
      } catch (error) {
        if (error.code !== 'ENOENT') throw error;
      }
    }
    return null;
  }

  async #atomicWrite(directory, key, value) {
    const temporary = path.join(directory, `.${key}.${randomUUID()}.tmp`);
    const target = path.join(directory, key);
    const handle = await open(temporary, 'wx', 0o600);
    try {
      await handle.writeFile(
        typeof value === 'number' ? `${value}\n` : `${JSON.stringify(value)}\n`,
        'utf8',
      );
      await handle.sync();
    } finally {
      await handle.close();
    }
    try {
      await rename(temporary, target);
      await fsyncDirectory(directory);
    } catch (error) {
      await rm(temporary, { force: true });
      throw error;
    }
  }

  #validateRecord(record) {
    if (!record || typeof record !== 'object') throw new TypeError('Invalid spool record');
    validateEvent(record.event, this.accountId);
    if (!Number.isSafeInteger(record.attempt) || record.attempt < 0) throw new TypeError('Invalid attempt');
    if (record.enqueue_order !== undefined
      && (!Number.isSafeInteger(record.enqueue_order) || record.enqueue_order < 1)) {
      throw new TypeError('Invalid enqueue order');
    }
  }

  async #nextCounter(counterPath, key) {
    let current = 0;
    try {
      current = Number((await readFile(counterPath, 'utf8')).trim());
    } catch (error) {
      if (error.code !== 'ENOENT') throw error;
    }
    if (!Number.isSafeInteger(current) || current < 0) throw new Error(`Corrupt spool ${key}`);
    const next = current + 1;
    await this.#atomicWrite(this.accountDir, key, next);
    return next;
  }

  #claimKey(claim) {
    if (!claim || typeof claim.key !== 'string' || !/^[a-f0-9]{64}\.json$/.test(claim.key)) {
      throw new TypeError('Invalid spool claim');
    }
    return claim.key;
  }

  async #ensureInitialized() {
    if (this.initialized) return;
    await secureDirectory(this.root);
    await Promise.all([
      this.accountDir,
      this.pendingDir,
      this.inflightDir,
      this.deadDir,
    ].map(secureDirectory));
    this.initialized = true;
  }

  #serial(callback) {
    const next = this.operation.then(callback, callback);
    this.operation = next.catch(() => {});
    return next;
  }
}
