import { isTauri } from '@tauri-apps/api/core'

/**
 * 解析后端 API 基址。
 *
 * 权威变量名是 `VITE_API_BASE_URL`（SDD VCL-002：前端直连自托管 API 的
 * 构建期开关）。历史实现使用 `VITE_API_BASE`，为避免已有部署静默失效，
 * 这里保留为兼容别名，但会给出弃用告警。
 * 两者都未设置时回退相对路径 `/api`，对应自托管同源或反代部署。
 */
export function resolveApiBase(env = import.meta.env ?? {}) {
  const canonical = typeof env.VITE_API_BASE_URL === 'string' ? env.VITE_API_BASE_URL.trim() : ''
  if (canonical) return canonical.replace(/\/$/, '')

  const legacy = typeof env.VITE_API_BASE === 'string' ? env.VITE_API_BASE.trim() : ''
  if (legacy) {
    console.warn(
      '[api] VITE_API_BASE 已弃用，请改用 VITE_API_BASE_URL（SDD VCL-002）。' +
        ' 当前仍按旧值工作以保证向后兼容。',
    )
    return legacy.replace(/\/$/, '')
  }
  return '/api'
}

const DEFAULT_API_BASE = resolveApiBase()

let sessionToken = ''
let onUnauthorized = null

export function getApiBase() {
  return DEFAULT_API_BASE
}

export function setSessionToken(token) {
  sessionToken = token || ''
  requestCache.clear()
  inflightRequests.clear()
}

export function clearSessionToken() {
  setSessionToken('')
}

export function setUnauthorizedHandler(handler) {
  onUnauthorized = handler
}

function errorMessage(detail, envelope, status) {
  if (typeof detail === 'string' && detail.trim()) return detail
  if (detail && typeof detail === 'object') {
    if (typeof detail.message === 'string' && detail.message.trim()) return detail.message
    if (typeof detail.detail === 'string' && detail.detail.trim()) return detail.detail
  }
  if (typeof envelope?.message === 'string' && envelope.message.trim()) return envelope.message
  return `Request failed (${status})`
}

export class ApiError extends Error {
  constructor(status, detail, data = null) {
    const envelope = data?.error && typeof data.error === 'object' ? data.error : data
    super(errorMessage(detail, envelope, status))
    this.name = 'ApiError'
    this.status = status
    this.data = data
    this.code = envelope?.code || detail?.code || null
    this.retryable = Boolean(envelope?.retryable)
    this.requestId = envelope?.request_id || null
  }
}

function disabledLegacyFallback(path, status, data) {
  const code = data?.code || data?.error?.code || data?.detail?.code
  if (status !== 410 || code !== 'legacy_api_disabled') return undefined

  if (path === '/settings') {
    return { channels: [], aliases: {}, web_settings: {} }
  }
  if (path === '/dashboard') {
    return { stats: {}, recent_conversations: [], plugins_enabled: 0 }
  }
  if (path.startsWith('/conversations?')) {
    return { items: [], page: 1, page_size: 0, total: 0, has_more: false }
  }
  if (path.startsWith('/contacts?')) {
    return { items: [], page: 1, page_size: 0, total: 0, has_more: false }
  }
  return undefined
}

const requestCache = new Map()
const inflightRequests = new Map()

function cacheKey(path, method) { return `${sessionToken}:${method}:${path}` }

let tauriFetchLoader = null

async function loadTauriFetch() {
  if (!tauriFetchLoader) {
    tauriFetchLoader = import('@tauri-apps/plugin-http')
      .then(module => module.fetch)
      .catch(error => {
        tauriFetchLoader = null
        throw error
      })
  }
  return tauriFetchLoader
}

async function transportFetch(input, init) {
  // Browser requests never load the native HTTP plugin. Packaged Tauri apps
  // lazy-load it only for absolute remote URLs, keeping the Web entry bundle
  // independent from the desktop transport implementation.
  if (isTauri() && /^https?:\/\//i.test(input)) {
    const tauriFetch = await loadTauriFetch()
    return tauriFetch(input, init)
  }
  return globalThis.fetch(input, init)
}

async function request(path, { method = 'GET', body, signal, cacheTtlMs = 0, dedupe = true } = {}) {
  const key = cacheKey(path, method)
  if (method === 'GET' && cacheTtlMs > 0) {
    const cached = requestCache.get(key)
    if (cached && cached.expiresAt > Date.now()) return cached.data
  }
  if (method === 'GET' && dedupe && !signal && inflightRequests.has(key)) return inflightRequests.get(key)
  const operation = (async () => {
    if (method !== 'GET') {
      requestCache.clear()
      inflightRequests.clear()
    }
    const headers = {}
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  if (sessionToken) headers['x-session-token'] = sessionToken
  const res = await transportFetch(`${DEFAULT_API_BASE}${path}`, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
    signal,
  })
  let data = null
  try {
    data = await res.json()
  } catch {
    data = null
  }
  if (!res.ok) {
    const fallback = disabledLegacyFallback(path, res.status, data)
    if (fallback !== undefined) return fallback
    if (res.status === 401 && onUnauthorized) onUnauthorized()
    throw new ApiError(res.status, data?.detail, data)
  }
  return data
  })()
  if (method === 'GET' && dedupe && !signal) {
    inflightRequests.set(key, operation)
    operation.then(
      () => { if (inflightRequests.get(key) === operation) inflightRequests.delete(key) },
      () => { if (inflightRequests.get(key) === operation) inflightRequests.delete(key) },
    )
    if (cacheTtlMs > 0) operation.then(data => requestCache.set(key, { data, expiresAt: Date.now() + cacheTtlMs })).catch(() => {})
  }
  return operation
}

export const api = {
  get: (path, opts) => request(path, { ...opts, cacheTtlMs: opts?.cacheTtlMs ?? (path.startsWith('/v1/personas') ? 30_000 : 5_000), dedupe: opts?.dedupe !== false }),
  post: (path, body, opts) => request(path, { ...opts, method: 'POST', body }),
  put: (path, body, opts) => request(path, { ...opts, method: 'PUT', body }),
  patch: (path, body, opts) => request(path, { ...opts, method: 'PATCH', body }),
  delete: (path, bodyOrOpts, maybeOpts) => {
    const hasBody = bodyOrOpts && !('signal' in bodyOrOpts)
    return request(path, {
      ...(hasBody ? maybeOpts : bodyOrOpts),
      method: 'DELETE',
      body: hasBody ? bodyOrOpts : undefined,
    })
  },
}
