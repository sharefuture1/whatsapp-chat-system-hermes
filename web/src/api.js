const DEFAULT_API_BASE = import.meta.env.VITE_API_BASE?.replace(/\/$/, '') || '/api'

let sessionToken = ''
let onUnauthorized = null

export function getApiBase() {
  return DEFAULT_API_BASE
}

export function setSessionToken(token) {
  sessionToken = token || ''
}

export function clearSessionToken() {
  sessionToken = ''
}

export function setUnauthorizedHandler(handler) {
  onUnauthorized = handler
}

export class ApiError extends Error {
  constructor(status, detail, data = null) {
    const envelope = data?.error && typeof data.error === 'object' ? data.error : data
    super(detail || envelope?.message || `Request failed (${status})`)
    this.name = 'ApiError'
    this.status = status
    this.data = data
    this.code = envelope?.code || null
    this.retryable = Boolean(envelope?.retryable)
    this.requestId = envelope?.request_id || null
  }
}

async function request(path, { method = 'GET', body, signal } = {}) {
  const headers = {}
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  if (sessionToken) headers['x-session-token'] = sessionToken
  const res = await fetch(`${DEFAULT_API_BASE}${path}`, {
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
    if (res.status === 401 && onUnauthorized) onUnauthorized()
    throw new ApiError(res.status, data?.detail, data)
  }
  return data
}

export const api = {
  get: (path, opts) => request(path, opts),
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
