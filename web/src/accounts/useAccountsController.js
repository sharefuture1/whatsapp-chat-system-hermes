import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api'
import { normalizeAccount, summarizeAccounts } from './accountState'

function sameAccounts(previous, next) {
  if (previous === next) return true
  if (previous.length !== next.length) return false
  return previous.every((item, index) => JSON.stringify(item) === JSON.stringify(next[index]))
}

export function useAccountsController(active) {
  const [accounts, setAccounts] = useState([])
  const [selectedAccountId, setSelectedAccountIdState] = useState(() => localStorage.getItem('wa-selected-account') || 'all')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const requestRef = useRef(0)

  const refresh = useCallback(async ({ silent = false } = {}) => {
    const requestId = ++requestRef.current
    if (!silent) setLoading(true)
    try {
      const data = await api.get('/v1/accounts')
      if (requestId !== requestRef.current) return
      const next = (data?.items || []).map(normalizeAccount)
      setAccounts(prev => sameAccounts(prev, next) ? prev : next)
      setError('')
    } catch (err) {
      if (requestId === requestRef.current) setError(err?.message || 'accounts_load_failed')
      throw err
    } finally {
      if (!silent && requestId === requestRef.current) setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (!active) return undefined
    refresh().catch(() => {})
    const timer = setInterval(() => refresh({ silent: true }).catch(() => {}), 3000)
    return () => {
      clearInterval(timer)
      requestRef.current += 1
    }
  }, [active, refresh])

  const create = useCallback(async payload => {
    const result = await api.post('/v1/accounts', payload)
    refresh({ silent: true }).catch(() => {})
    return normalizeAccount(result)
  }, [refresh])

  const update = useCallback(async (accountId, payload) => {
    const result = await api.patch(`/v1/accounts/${encodeURIComponent(accountId)}`, payload)
    refresh({ silent: true }).catch(() => {})
    return normalizeAccount(result)
  }, [refresh])

  const connect = useCallback(async accountId => {
    const result = await api.post(`/v1/accounts/${encodeURIComponent(accountId)}/connect`, {})
    refresh({ silent: true }).catch(() => {})
    return result
  }, [refresh])

  const getQr = useCallback(accountId => (
    api.get(`/v1/accounts/${encodeURIComponent(accountId)}/qr`)
  ), [])

  const logout = useCallback(async accountId => {
    const result = await api.post(`/v1/accounts/${encodeURIComponent(accountId)}/logout`, {})
    refresh({ silent: true }).catch(() => {})
    return result
  }, [refresh])

  const remove = useCallback(async (accountId, payload) => {
    const result = await api.delete(`/v1/accounts/${encodeURIComponent(accountId)}`, payload)
    refresh({ silent: true }).catch(() => {})
    return result
  }, [refresh])

  const setSelectedAccountId = useCallback(accountId => {
    const value = accountId || 'all'
    localStorage.setItem('wa-selected-account', value)
    setSelectedAccountIdState(value)
  }, [])

  return {
    accounts,
    selectedAccountId,
    setSelectedAccountId,
    summary: useMemo(() => summarizeAccounts(accounts), [accounts]),
    loading,
    error,
    refresh,
    create,
    update,
    connect,
    getQr,
    logout,
    remove,
  }
}
