import { useCallback, useEffect, useMemo, useState } from 'react'
import { api, setSessionToken, setUnauthorizedHandler } from './api'
import AliasPanel from './components/AliasPanel'
import ConversationDetail from './components/ConversationDetail'
import ConversationList from './components/ConversationList'
import LoginScreen from './components/LoginScreen'
import SettingsPanel from './components/SettingsPanel'
import StatCard from './components/StatCard'
import TopBar from './components/TopBar'

const TOKEN_KEY = 'chat-system-token'

export default function App() {
  const [sessionToken, setToken] = useState(() => {
    const stored = localStorage.getItem(TOKEN_KEY) || ''
    setSessionToken(stored)
    return stored
  })
  const [loginError, setLoginError] = useState('')
  const [loginLoading, setLoginLoading] = useState(false)
  const [banner, setBanner] = useState('')
  const [health, setHealth] = useState(null)
  const [dashboard, setDashboard] = useState(null)
  const [conversations, setConversations] = useState([])
  const [selectedId, setSelectedId] = useState('')
  const [detail, setDetail] = useState(null)
  const [settings, setSettings] = useState({ channels: [], aliases: {}, web_settings: {} })
  const [saving, setSaving] = useState(false)
  const [sending, setSending] = useState(false)
  const [sendingMeta, setSendingMeta] = useState(null)
  const [jobRunning, setJobRunning] = useState('')
  const [query, setQuery] = useState('')

  const logout = useCallback(() => {
    localStorage.removeItem(TOKEN_KEY)
    setSessionToken('')
    setToken('')
    setDetail(null)
    setDashboard(null)
    setConversations([])
  }, [])

  useEffect(() => {
    setUnauthorizedHandler(logout)
  }, [logout])

  const showError = e => setBanner(e?.message || 'Request failed')

  const handleLogin = async (password) => {
    setLoginLoading(true)
    setLoginError('')
    try {
      const data = await api.post('/login', { password })
      localStorage.setItem(TOKEN_KEY, data.session_token)
      setSessionToken(data.session_token)
      setToken(data.session_token)
    } catch (e) {
      setLoginError(e.message)
    } finally {
      setLoginLoading(false)
    }
  }

  const fetchDetail = useCallback(async (userId) => {
    if (!userId) return null
    return api.get(`/conversations/${encodeURIComponent(userId)}`)
  }, [])

  // Reloads only conversation-derived data; settings and health stay untouched.
  const refreshWorkspace = useCallback(async ({ silent = false } = {}) => {
    try {
      const [dashboardRes, convRes] = await Promise.all([
        api.get('/dashboard'),
        api.get('/conversations'),
      ])
      setDashboard(dashboardRes)
      setConversations(convRes)
      setSelectedId(prev => {
        const current = prev || convRes[0]?.user_id || ''
        if (current) fetchDetail(current).then(setDetail).catch(() => {})
        return current
      })
    } catch (e) {
      if (!silent) showError(e)
    }
  }, [fetchDetail])

  const refreshSettings = useCallback(async () => {
    setSettings(await api.get('/settings'))
  }, [])

  useEffect(() => {
    api.get('/health').then(setHealth).catch(() => {})
  }, [])

  useEffect(() => {
    if (!sessionToken) return
    refreshSettings().catch(showError)
    refreshWorkspace()
  }, [sessionToken, refreshSettings, refreshWorkspace])

  useEffect(() => {
    if (!selectedId || !sessionToken) return
    fetchDetail(selectedId).then(setDetail).catch(showError)
  }, [selectedId, sessionToken, fetchDetail])

  // Background polling driven by the configurable ui.auto_refresh_seconds setting.
  const autoSeconds = Number(settings.web_settings?.ui?.auto_refresh_seconds) || 0
  useEffect(() => {
    if (!sessionToken || autoSeconds <= 0) return
    const interval = setInterval(() => refreshWorkspace({ silent: true }), Math.max(3, autoSeconds) * 1000)
    return () => clearInterval(interval)
  }, [sessionToken, autoSeconds, refreshWorkspace])

  const saveSettings = async (payload, done) => {
    setSaving(true)
    try {
      await api.put('/settings', payload)
      await refreshSettings()
      done?.()
    } catch (e) {
      showError(e)
    } finally {
      setSaving(false)
    }
  }

  const sendReply = async (target, message, mode, done) => {
    setSending(true)
    try {
      const data = await api.post('/reply', { target, message, mode, preview_only: false })
      setSendingMeta({ mode: data.mode, language: data.rewrite?.language || 'direct' })
      await refreshWorkspace()
      done?.()
    } catch (e) {
      showError(e)
    } finally {
      setSending(false)
    }
  }

  const hideMessage = async (messageId) => {
    try {
      await api.post('/messages/hide', { message_ids: [messageId] })
      if (selectedId) setDetail(await fetchDetail(selectedId))
    } catch (e) {
      showError(e)
    }
  }

  const hideLatest = async (userId, count) => {
    if (!detail?.messages?.length) return
    const ids = detail.messages.slice(-count).map(m => m.message_id || m.timestamp)
    try {
      await api.post('/messages/hide', { message_ids: ids })
      setDetail(await fetchDetail(userId))
    } catch (e) {
      showError(e)
    }
  }

  const runJob = async job => {
    setJobRunning(job)
    try {
      await api.post('/jobs/run', { job })
      await refreshWorkspace()
    } catch (e) {
      showError(e)
    } finally {
      setJobRunning('')
    }
  }

  const aliases = useMemo(() => Object.entries(settings.aliases || {}), [settings.aliases])
  const filteredConversations = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return conversations
    return conversations.filter(item =>
      item.user_name?.toLowerCase().includes(q) ||
      item.user_id?.toLowerCase().includes(q) ||
      item.last_message?.toLowerCase().includes(q)
    )
  }, [conversations, query])

  const stats = dashboard?.stats || {}

  if (!sessionToken) {
    return <LoginScreen onLogin={handleLogin} error={loginError} loading={loginLoading} />
  }

  return (
    <div className="app-shell pro ultra-shell">
      <TopBar health={health} onRunJob={runJob} runningJob={jobRunning} onLogout={logout} />

      {banner ? (
        <div className="error-banner" role="alert">
          <span>{banner}</span>
          <button className="ghost-btn small-btn" onClick={() => setBanner('')}>Dismiss</button>
        </div>
      ) : null}

      <section className="stats-grid premium-stats">
        <StatCard label="Total conversations" value={stats.total_conversations ?? '-'} hint="Tracked cross-channel user threads" />
        <StatCard label="High priority" value={stats.high_priority_conversations ?? '-'} hint="Needs closer human attention" />
        <StatCard label="Total messages" value={stats.total_messages ?? '-'} hint="Messages currently indexed" />
        <StatCard label="Active admin channels" value={stats.active_admin_channels ?? '-'} hint={(stats.channel_names || []).join(', ') || 'No active routes'} />
      </section>

      <main className="pro-grid premium-layout">
        <ConversationList conversations={filteredConversations} selectedId={selectedId} onSelect={setSelectedId} query={query} onQueryChange={setQuery} />
        <ConversationDetail detail={detail} onReply={sendReply} onHideMessage={hideMessage} onHideLatest={hideLatest} sending={sending} sendingMeta={sendingMeta} uiSettings={settings.web_settings} />
        <div className="side-stack pro-side">
          <SettingsPanel settings={settings.web_settings} channels={settings.channels || []} onSave={saveSettings} saving={saving} />
          <AliasPanel aliases={aliases} />
        </div>
      </main>
    </div>
  )
}
