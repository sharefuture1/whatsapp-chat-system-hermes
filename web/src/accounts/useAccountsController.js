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
  const refreshPromiseRef = useRef(null)

  const refresh = useCallback(({ silent = false } = {}) => {
    if (refreshPromiseRef.current) return refreshPromiseRef.current
    const requestId = ++requestRef.current
    if (!silent) setLoading(true)
    const run = (async () => {
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
    })()
    refreshPromiseRef.current = run
    run.then(
      () => { if (refreshPromiseRef.current === run) refreshPromiseRef.current = null },
      () => { if (refreshPromiseRef.current === run) refreshPromiseRef.current = null },
    )
    return run
  }, [])

  useEffect(() => {
    if (!active) return undefined
    let timer = null
    let stopped = false
    let running = false
    const clearTimer = () => {
      if (timer) clearTimeout(timer)
      timer = null
    }
    const schedule = (wait = 3000) => {
      if (stopped || document.visibilityState !== 'visible') return
      clearTimer()
      timer = setTimeout(run, wait)
    }
    const run = async () => {
      timer = null
      if (stopped || running || document.visibilityState !== 'visible') return
      running = true
      await refresh({ silent: true }).catch(() => {})
      running = false
      schedule()
    }
    const onVisibilityChange = () => {
      if (document.visibilityState === 'visible') schedule(0)
      else clearTimer()
    }
    refresh().catch(() => {})
    schedule()
    document.addEventListener('visibilitychange', onVisibilityChange)
    return () => {
      stopped = true
      clearTimer()
      document.removeEventListener('visibilitychange', onVisibilityChange)
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
