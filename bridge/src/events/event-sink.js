const DEFAULT_URL = 'http://127.0.0.1:8792/internal/events/whatsapp';

const defaultScheduler = Object.freeze({
  setTimeout: (callback, delay) => setTimeout(callback, delay),
  clearTimeout: (timer) => clearTimeout(timer),
});

function defaultBackoff(attempt) {
  return Math.min(60_000, 1_000 * (2 ** Math.max(0, attempt - 1)));
}

export class EventSink {
  constructor({
    spool,
    token,
    url = DEFAULT_URL,
    fetchImpl = globalThis.fetch,
    timeoutMs = 10_000,
    pollIntervalMs = 1_000,
    backoff = defaultBackoff,
    scheduler = defaultScheduler,
  }) {
    if (!spool || typeof spool.append !== 'function') throw new TypeError('Event spool is required');
    if (typeof token !== 'string' || token.trim().length === 0) {
      throw new TypeError('Internal event token is required');
    }
    if (typeof fetchImpl !== 'function') throw new TypeError('fetch implementation is required');
    this.spool = spool;
    this.token = token.trim();
    this.url = url;
    this.fetchImpl = fetchImpl;
    this.timeoutMs = timeoutMs;
    this.pollIntervalMs = pollIntervalMs;
    this.backoff = backoff;
    this.scheduler = scheduler;
    this.running = false;
    this.timer = null;
    this.flushPromise = null;
  }

  async initialize() {
    await this.spool.initialize();
  }

  async enqueue(event) {
    await this.spool.append(event);
    await this.flushOnce();
  }

  async nextSequence() {
    return this.spool.nextSequence();
  }

  async start() {
    if (this.running) return;
    await this.initialize();
    this.running = true;
    await this.#drainAvailable();
    if (this.running) this.#schedule();
  }

  async stop() {
    this.running = false;
    if (this.timer !== null) {
      this.scheduler.clearTimeout(this.timer);
      this.timer = null;
    }
    if (this.flushPromise) await this.flushPromise;
  }

  flushOnce() {
    if (this.flushPromise) return this.flushPromise;
    const operation = this.#flushOne();
    const wrapped = operation.finally(() => {
      if (this.flushPromise === wrapped) this.flushPromise = null;
    });
    this.flushPromise = wrapped;
    return wrapped;
  }

  async #drainAvailable() {
    while (await this.flushOnce()) {
      // Continue until the queue is empty or a retained/dead event stops this pass.
    }
  }

  async #flushOne() {
    const claim = await this.spool.claim();
    if (!claim) return false;

    let response;
    try {
      response = await this.#post(claim.event);
    } catch (error) {
      await this.#retain(claim, error?.message || 'network_error');
      return false;
    }

    if (response.status === 200) {
      let body;
      try {
        body = await response.json();
      } catch {
        await this.#retain(claim, 'invalid_200_response');
        return false;
      }
      if (body?.accepted === true && (body.duplicate === true || body.duplicate === false)) {
        await this.spool.complete(claim);
        return true;
      }
      await this.#retain(claim, 'unaccepted_200_response');
      return false;
    }

    if (response.status === 422) {
      await this.spool.deadLetter(claim, { error: 'HTTP 422' });
      return false;
    }

    if (response.status === 409) {
      let body = null;
      try {
        body = await response.json();
      } catch {
        // A 409 without an explicit terminal contract is safe to retry. This
        // covers the normal race where a receipt arrives before the API has
        // persisted the outbound WhatsApp message ID.
      }
      if (body?.error?.retryable === false) {
        await this.spool.deadLetter(claim, { error: 'HTTP 409 non_retryable' });
        return false;
      }
      await this.#retain(claim, 'HTTP 409 retryable');
      return false;
    }

    await this.#retain(claim, `HTTP ${response.status}`);
    return false;
  }

  async #post(event) {
    const controller = new AbortController();
    const timer = this.scheduler.setTimeout(() => controller.abort(), this.timeoutMs);
    try {
      return await this.fetchImpl(this.url, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Internal-Token': this.token,
          'X-Request-ID': event.event_id,
        },
        body: JSON.stringify(event),
        signal: controller.signal,
      });
    } finally {
      this.scheduler.clearTimeout(timer);
    }
  }

  async #retain(claim, error) {
    const nextAttempt = Number(claim.attempt ?? 0) + 1;
    const delayMs = Math.max(0, Number(this.backoff(nextAttempt, claim.event)) || 0);
    await this.spool.release(claim, { error, delayMs });
  }

  #schedule() {
    if (!this.running || this.timer !== null) return;
    this.timer = this.scheduler.setTimeout(async () => {
      this.timer = null;
      try {
        await this.#drainAvailable();
      } finally {
        this.#schedule();
      }
    }, this.pollIntervalMs);
  }
}

export { DEFAULT_URL as DEFAULT_EVENT_URL };
