export const PRODUCTION_API_BASE = 'https://whats.wending.ai/api'

function normalizeBase(value) {
  if (typeof value !== 'string') return ''
  return value.trim().replace(/\/+$/, '')
}

/**
 * Resolve the public API base used at build time.
 *
 * Vercel Production is intentionally zero-config for the canonical public API.
 * Preview must never inherit or explicitly target the production API, otherwise
 * a UI smoke deployment could mutate production data with a real operator token.
 * Non-Vercel builds keep their explicit value (or empty, which lets api.js fall
 * back to the same-origin /api path for self-hosted development/rollback).
 */
export function resolveDeploymentApiBase({ vercelEnv = '', configuredBase = '' } = {}) {
  const target = String(vercelEnv || '').trim().toLowerCase()
  const configured = normalizeBase(configuredBase)

  if (target === 'production') {
    if (configured && configured !== PRODUCTION_API_BASE) {
      throw new Error(
        `Vercel Production API base must be ${PRODUCTION_API_BASE}; received ${configured}`,
      )
    }
    return PRODUCTION_API_BASE
  }

  if (target === 'preview' && configured === PRODUCTION_API_BASE) {
    throw new Error(
      'Vercel Preview must not target the production API; use a staging API or leave VITE_API_BASE_URL unset',
    )
  }

  return configured
}
