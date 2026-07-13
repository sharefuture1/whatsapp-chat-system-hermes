import path from 'node:path';
import { chmod, mkdir, readFile, rename, writeFile } from 'node:fs/promises';

const SAFE_KEY = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,254}$/;

export class SendReceiptStore {
  constructor(spoolDir, { maxEntries = 5000 } = {}) {
    this.filePath = path.join(spoolDir, 'send-receipts.json');
    this.maxEntries = Math.max(100, Math.min(Number(maxEntries) || 5000, 50_000));
    this.entries = new Map();
    this.writeWork = Promise.resolve();
  }

  async start() {
    await mkdir(path.dirname(this.filePath), { recursive: true, mode: 0o700 });
    try {
      const parsed = JSON.parse(await readFile(this.filePath, 'utf8'));
      for (const item of Array.isArray(parsed?.items) ? parsed.items : []) {
        if (!SAFE_KEY.test(item?.key ?? '')) continue;
        if (typeof item?.message_id !== 'string' || !item.message_id.trim()) continue;
        this.entries.set(item.key, {
          message_id: item.message_id,
          created_at: Number(item.created_at) || Date.now(),
        });
      }
      this.#trim();
    } catch (error) {
      if (error?.code !== 'ENOENT') throw error;
    }
  }

  validateKey(value) {
    if (value === null || value === undefined || value === '') return null;
    if (typeof value !== 'string' || !SAFE_KEY.test(value)) {
      const error = new Error('Invalid idempotency_key');
      error.code = 'invalid_idempotency_key';
      throw error;
    }
    return value;
  }

  get(key) {
    const normalized = this.validateKey(key);
    return normalized ? this.entries.get(normalized)?.message_id ?? null : null;
  }

  async put(key, messageId) {
    const normalized = this.validateKey(key);
    if (!normalized) return;
    this.entries.delete(normalized);
    this.entries.set(normalized, { message_id: messageId, created_at: Date.now() });
    this.#trim();
    const prior = this.writeWork.catch(() => undefined);
    this.writeWork = prior.then(() => this.#flush());
    await this.writeWork;
  }

  #trim() {
    while (this.entries.size > this.maxEntries) {
      this.entries.delete(this.entries.keys().next().value);
    }
  }

  async #flush() {
    const temporary = `${this.filePath}.${process.pid}.tmp`;
    const payload = JSON.stringify({
      version: 1,
      items: [...this.entries.entries()].map(([key, value]) => ({ key, ...value })),
    });
    await writeFile(temporary, payload, { encoding: 'utf8', mode: 0o600 });
    await chmod(temporary, 0o600);
    await rename(temporary, this.filePath);
    await chmod(this.filePath, 0o600);
  }
}
