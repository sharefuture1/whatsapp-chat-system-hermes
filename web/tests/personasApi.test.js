import test from 'node:test'
import assert from 'node:assert/strict'
import { ApiError, setSessionToken } from '../src/api.js'

const personasModule = await import('../src/personas.js')
const { fetchPersonaCatalog, assignPersona, setPersonaPluginEnabled } = personasModule

function createJsonResponse(status, body) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  }
}

function installFetch(impl) {
  const original = globalThis.fetch
  globalThis.fetch = impl
  return () => {
    globalThis.fetch = original
  }
}

test('fetchPersonaCatalog uses the authenticated V1 client and exposes Tong Jincheng', async () => {
  const calls = []
  setSessionToken('persona-test-token')
  const restore = installFetch(async (url, options = {}) => {
    calls.push({ url: String(url), method: options.method || 'GET', headers: options.headers })
    return createJsonResponse(200, {
      items: [
        { id: 'tong-jincheng', name: '童锦程·直球关系顾问', description: 'd', category: 'relationship', accent: 'a', available: true },
        { id: 'professional-service', name: '专业服务顾问', description: 'd', category: 'service', accent: 'a', available: true },
        { id: 'mature-uncle', name: '成熟长辈', description: 'd', category: 'companion', accent: 'a', available: true },
      ],
      contact_assignments: { '12345@lid': 'tong-jincheng' },
      plugin_enabled: true,
    })
  })

  try {
    const result = await fetchPersonaCatalog()
    assert.equal(calls.length, 1)
    assert.equal(calls[0].url, '/api/v1/personas')
    assert.equal(calls[0].method, 'GET')
    assert.equal(calls[0].headers['x-session-token'], 'persona-test-token')
    assert.equal(result.items.length, 3)
    assert.equal(result.items[0].id, 'tong-jincheng')
    assert.equal(result.items[0].name, '童锦程·直球关系顾问')
    assert.equal(result.available, true)
    assert.equal(result.plugin_enabled, true)
    assert.equal(result.contact_assignments['12345@lid'], 'tong-jincheng')
  } finally {
    setSessionToken('')
    restore()
  }
})

test('fetchPersonaCatalog surfaces an authenticated API error instead of silently hiding personas', async () => {
  const restore = installFetch(async () => createJsonResponse(401, { detail: 'Unauthorized' }))
  try {
    await assert.rejects(fetchPersonaCatalog(), ApiError)
  } finally {
    restore()
  }
})

test('assignPersona default clears the contact persona via authenticated V1', async () => {
  const calls = []
  const restore = installFetch(async (url, options = {}) => {
    calls.push({ url: String(url), method: options.method || 'GET', body: options.body ? JSON.parse(options.body) : null })
    return createJsonResponse(200, { contact_id: '12345@lid', persona_id: 'default' })
  })

  try {
    const result = await assignPersona('12345@lid', 'default')
    assert.equal(calls[0].method, 'PUT')
    assert.equal(calls[0].url, '/api/v1/contacts/12345%40lid/persona')
    assert.deepEqual(calls[0].body, { persona_id: 'default' })
    assert.equal(result.persona_id, 'default')
  } finally {
    restore()
  }
})

test('setPersonaPluginEnabled issues an authenticated PUT with the boolean body', async () => {
  const calls = []
  const restore = installFetch(async (url, options = {}) => {
    calls.push({ url: String(url), method: options.method || 'GET', body: options.body ? JSON.parse(options.body) : null })
    return createJsonResponse(200, { id: 'tong-jincheng', enabled: false })
  })

  try {
    const result = await setPersonaPluginEnabled('tong-jincheng', false)
    assert.equal(calls[0].method, 'PUT')
    assert.equal(calls[0].url, '/api/v1/personas/tong-jincheng/enable')
    assert.deepEqual(calls[0].body, { enabled: false })
    assert.equal(result.enabled, false)
  } finally {
    restore()
  }
})
