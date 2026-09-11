import assert from 'node:assert/strict'
import test from 'node:test'
import { api, setSessionToken, setUnauthorizedHandler } from '../src/api.js'

const response = (data, status = 200) => ({ ok: status < 400, status, json: async () => data })
function setup(t) {
  const originalFetch = globalThis.fetch
  setSessionToken('user-a-test-session')
  setUnauthorizedHandler(null)
  t.after(() => { globalThis.fetch = originalFetch; setUnauthorizedHandler(null); setSessionToken('') })
}

test('SEC-CACHE-001 a late 401 cannot sign out a newer session', async t => {
  setup(t)
  let finish
  let unauthorized = 0
  setUnauthorizedHandler(() => { unauthorized += 1 })
  globalThis.fetch = () => new Promise(resolve => { finish = resolve })
  const pending = api.get('/v1/test-old-session', { cacheTtlMs: 0 })
  setSessionToken('user-b-test-session')
  finish(response({ detail: 'Unauthorized' }, 401))
  await assert.rejects(pending, error => error.code === 'stale_session')
  assert.equal(unauthorized, 0)
})

test('SEC-CACHE-001 a GET started before a mutation cannot repopulate its cache', async t => {
  setup(t)
  let finish
  globalThis.fetch = (url, init) => init.method === 'GET'
    ? new Promise(resolve => { finish = resolve }) : Promise.resolve(response({ saved: true }))
  const old = api.get('/v1/test-mutated')
  await api.post('/v1/test-mutated', { value: 'new' })
  finish(response({ value: 'old' }))
  await assert.rejects(old, error => error.code === 'stale_response')
  globalThis.fetch = async () => response({ value: 'new' })
  assert.deepEqual(await api.get('/v1/test-mutated'), { value: 'new' })
})

test('SEC-CACHE-001 deadline includes reading the response body', async t => {
  setup(t)
  globalThis.fetch = async (_url, { signal }) => ({ ok: true, status: 200,
    json: () => new Promise((_resolve, reject) => signal?.addEventListener('abort',
      () => reject(new DOMException('aborted', 'AbortError')), { once: true })),
  })
  const result = await Promise.race([
    api.get('/v1/test-body-timeout', { timeoutMs: 5, cacheTtlMs: 0 }).catch(error => error),
    new Promise(resolve => setTimeout(() => resolve({ code: 'missing_deadline' }), 80)),
  ])
  assert.equal(result.code, 'request_timeout')
})

test('SEC-CACHE-001 explicit cancellation is not reported as a timeout', async t => {
  setup(t)
  globalThis.fetch = (_url, { signal }) => new Promise((_resolve, reject) =>
    signal.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')), { once: true }))
  const controller = new AbortController()
  const result = api.get('/v1/test-cancel', { signal: controller.signal, timeoutMs: 100 }).catch(error => error)
  controller.abort()
  assert.equal((await result).code, 'request_cancelled')
})
