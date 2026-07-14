import assert from 'node:assert/strict'
import test from 'node:test'

import { api, ApiError } from '../src/api.js'

function response(status, payload) {
  return {
    ok: status >= 200 && status < 300,
    status,
    async json() { return payload },
  }
}

test('standalone mode degrades explicitly disabled legacy list endpoints', async () => {
  const originalFetch = globalThis.fetch
  globalThis.fetch = async () => response(410, { code: 'legacy_api_disabled' })
  try {
    assert.deepEqual(await api.get('/conversations?page=1&page_size=30'), {
      items: [],
      page: 1,
      page_size: 0,
      total: 0,
      has_more: false,
    })
    assert.deepEqual(await api.get('/contacts?page=1&page_size=500'), {
      items: [],
      page: 1,
      page_size: 0,
      total: 0,
      has_more: false,
    })
    assert.deepEqual(await api.get('/settings'), {
      channels: [],
      aliases: {},
      web_settings: {},
    })
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('non-legacy errors retain structured messages and codes', async () => {
  const originalFetch = globalThis.fetch
  globalThis.fetch = async () => response(503, {
    detail: {
      code: 'scheduler_not_connected',
      message: 'Scheduler worker is not connected',
    },
  })
  try {
    await assert.rejects(
      () => api.post('/schedule', {}),
      error => {
        assert.ok(error instanceof ApiError)
        assert.equal(error.message, 'Scheduler worker is not connected')
        assert.equal(error.code, 'scheduler_not_connected')
        assert.equal(error.status, 503)
        return true
      },
    )
  } finally {
    globalThis.fetch = originalFetch
  }
})
