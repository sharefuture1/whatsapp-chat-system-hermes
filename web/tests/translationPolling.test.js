import test from 'node:test'
import assert from 'node:assert/strict'
import { waitForTranslationBatch } from '../src/translationPolling.js'
import { api, setSessionToken } from '../src/api.js'

test('FR-AI-014: wait for actual completion beyond the old two-second window', async () => {
  let calls = 0
  const delays = []
  const result = await waitForTranslationBatch({
    check: async () => ({ status: ++calls < 5 ? 'running' : 'completed' }),
    pause: async ms => { delays.push(ms) },
  })
  assert.equal(result.status, 'completed')
  assert.equal(calls, 5)
  assert.ok(delays.reduce((a, b) => a + b, 0) > 1750)
})

test('FR-AI-014: failed batches are not retried forever or reported as success', async () => {
  let calls = 0
  const result = await waitForTranslationBatch({
    check: async () => { calls++; return { status: 'failed' } },
    pause: async () => {},
  })
  assert.equal(calls, 1)
  assert.equal(result.status, 'failed')
})

test('FR-AI-014: abort prevents further polling on conversation switch', async () => {
  const controller = new AbortController()
  controller.abort()
  await assert.rejects(waitForTranslationBatch({
    signal: controller.signal, check: () => assert.fail('must not request'),
  }), { name: 'AbortError' })
})

test('PERF: fresh translation reads bypass in-flight dedupe', async () => {
  const old = globalThis.fetch
  setSessionToken('test-polling-session')
  let release
  let calls = 0
  globalThis.fetch = async () => {
    calls++
    const id = calls
    if (id === 1) await new Promise(resolve => { release = resolve })
    return { ok: true, status: 200, json: async () => ({ id }) }
  }
  try {
    const cached = api.get('/v1/poll-test')
    const fresh = api.get('/v1/poll-test', { cacheTtlMs: 0, dedupe: false })
    assert.equal(calls, 2)
    assert.equal((await fresh).id, 2)
    release()
    await cached
  } finally {
    release?.()
    setSessionToken('')
    globalThis.fetch = old
  }
})
