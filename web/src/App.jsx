import { useCallback, useEffect, useMemo, useState } from 'react'
import { api, setSessionToken, setUnauthorizedHandler, clearSessionToken, getApiBase } from './api'
import { SettingsProvider, useSettings } from './settings'
import AliasPanel from './components/AliasPanel'
import ConversationDetail from './components/ConversationDetail'
import ConversationList from './components/ConversationList'
import LoginScreen from './components/LoginScreen'
import RecentStrip from './components/RecentStrip'
import SettingsPanel from './components/SettingsPanel'
import StatCard from './components/StatCard'
import TopBar from './components/TopBar'
import MobileNav from './components/MobileNav'

const TOKEN_KEY = 'chat-system-token'
const PAGE_SIZE = 50
const PIN_KEY = 'chat-system-pinned'

function AppInner() {
  const { t } = useSettings()
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
  const [conversationsTotal, setConversationsTotal] = useState(0)
  const [conversationsHasMore, setConversationsHasMore] = useState(false)
  const [conversationsPage, setConversationsPage] = useState(1)
  const [loadingMore, setLoadingMore] = useState(false)
  const [selectedId, setSelectedId] = useState('')
  const [detail, setDetail] = useState(null)
  const [settings, setSettings] = useState({ channels: [], aliases: {}, web_settings: {} })
  const [saving, setSaving] = useState(false)
  const [sending, setSending] = useState(false)
  const [sendingMeta, setSendingMeta] = useState(null)
  const [jobRunning, setJobRunning] = useState('')
  const [query, setQuery] = useState('')
  const [globalQuery, setGlobalQuery] = useState('')
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [navOpen, setNavOpen] = useState(false)
  const [activeTab, setActiveTab] = useState('inbox')
  const [pinned, setPinned] = useState(() => {
    try { return JSON.parse(localStorage.getItem(PIN_KEY) || '[]') } catch { return [] }
  })
  const [globalResults, setGlobalResults] = useState([])
  const [globalSearching, setGlobalSearching] = useState(false)

  const logout = useCallback(async () => {
    try {
      if (sessionToken) await api.post('/logout', {})
    } catch {
      // ignore logout errors
    }
    localStorage.removeItem(TOKEN_KEY)
    clearSessionToken()
    setToken('')
    setDetail(null)
    setDashboard(null)
    setConversations([])
  }, [sessionToken])

  useEffect(() => {
    setUnauthorizedHandler(logout)
  }, [logout])

  useEffect(() => {
    if (!banner) return
    const id = setTimeout(() => setBanner(''), 4000)
    return () => clearTimeout(id)
  }, [banner])

  const showError = e => setBanner(e?.message || t('error'))

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

  const fetchConversationsPage = useCallback(async (page, append = false) => {
    const res = await api.get(`/conversations?page=${page}&page_size=${PAGE_SIZE}`)
    if (append) {
      setConversations(prev => [...prev, ...(res.items || [])])
    } else {
      setConversations(res.items || [])
    }
    setConversationsTotal(res.total || 0)
    setConversationsHasMore(Boolean(res.has_more))
    setConversationsPage(res.page || page)
    return res
  }, [])

  const refreshWorkspace = useCallback(async ({ silent = false } = {}) => {
    try {
      const [dashboardRes, convRes] = await Promise.all([
        api.get('/dashboard'),
        fetchConversationsPage(1, false),
      ])
      setDashboard(dashboardRes)
      setSelectedId(prev => {
        const current = prev || convRes.items?.[0]?.user_id || ''
        if (current) fetchDetail(current).then(setDetail).catch(() => {})
        return current
      })
    } catch (e) {
      if (!silent) showError(e)
    }
  }, [fetchDetail, fetchConversationsPage])

  const loadMoreConversations = useCallback(async () => {
    if (loadingMore || !conversationsHasMore) return
    setLoadingMore(true)
    try {
      await fetchConversationsPage(conversationsPage + 1, true)
    } catch (e) {
      showError(e)
    } finally {
      setLoadingMore(false)
    }
  }, [conversationsHasMore, conversationsPage, fetchConversationsPage, loadingMore])

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

  useEffect(() => {
    if (!globalQuery.trim() || !sessionToken) {
      setGlobalResults([])
      return
    }
    let cancelled = false
    const timer = setTimeout(async () => {
      setGlobalSearching(true)
      try {
        const res = await api.get(`/search?q=${encodeURIComponent(globalQuery.trim())}`)
        if (!cancelled) setGlobalResults(res.results || [])
      } catch {
        if (!cancelled) setGlobalResults([])
      } finally {
        if (!cancelled) setGlobalSearching(false)
      }
    }, 250)
    return () => { cancelled = true; clearTimeout(timer) }
  }, [globalQuery, sessionToken])

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
    const ids = detail.messages.filter(m => !m.hidden).slice(-count).map(m => m.message_id)
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

  const togglePin = useCallback((userId) => {
    setPinned(prev => {
      const next = prev.find(p => p.user_id === userId)
        ? prev.filter(p => p.user_id !== userId)
        : [...prev, { user_id: userId }]
      localStorage.setItem(PIN_KEY, JSON.stringify(next))
      return next
    })
  }, [])

  const pinnedItems = useMemo(() => {
    const map = new Map(conversations.map(c => [c.user_id, c]))
    return pinned.map(p => map.get(p.user_id) || p).filter(Boolean)
  }, [pinned, conversations])

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
  const recent = dashboard?.recent_conversations || []

  if (!sessionToken) {
    return <LoginScreen onLogin={handleLogin} error={loginError} loading={loginLoading} />
  }

  return (
    <div className="app-shell">
      <TopBar
        health={health}
        onRunJob={runJob}
        runningJob={jobRunning}
        onLogout={logout}
        onOpenSettings={() => setSettingsOpen(true)}
        onOpenMobileNav={() => setNavOpen(true)}
      />

      {banner ? (
        <div className="app-banner" role="alert">
          <span>{banner}</span>
          <button className="ghost-btn small-btn" onClick={() => setBanner('')}>{t('dismiss')}</button>
        </div>
      ) : null}

      <section className="stats-grid">
        <StatCard label={t('totalConversations')} value={stats.total_conversations ?? '-'} hint={t('hintTracked')} />
        <StatCard label={t('highPriority')} value={stats.high_priority_conversations ?? '-'} hint={t('hintHighPriority')} />
        <StatCard label={t('totalMessages')} value={stats.total_messages ?? '-'} hint={t('hintIndexed')} />
        <StatCard label={t('activeChannels')} value={stats.active_admin_channels ?? '-'} hint={(stats.channel_names || []).join(', ') || `${t('apiBase')}: ${getApiBase()}`} />
      </section>

      <div className="global-search-row">
        <input
          className="global-search"
          value={globalQuery}
          onChange={e => setGlobalQuery(e.target.value)}
          placeholder={t('globalSearch')}
        />
        {globalSearching ? <span className="subtle">{t('loading')}</span> : null}
        {globalQuery && !globalSearching && globalResults.length > 0 ? (
          <span className="subtle">{globalResults.length} {t('matches')}</span>
        ) : null}
        {globalQuery && !globalSearching && globalResults.length === 0 ? (
          <span className="subtle">{t('noMessages')}</span>
        ) : null}
      </div>
      {globalQuery && globalResults.length > 0 ? (
        <ul className="global-search-results">
          {globalResults.slice(0, 8).map(r => (
            <li key={`g-${r.message_id}`}>
              <button onClick={() => { setSelectedId(r.user_id); setActiveTab('detail') }}>
                <div className="global-result-topline">
                  <strong>{r.user_name}</strong>
                  <span className="subtle">{r.role}</span>
                </div>
                <div className="global-result-content">{r.snippet || r.content}</div>
              </button>
            </li>
          ))}
        </ul>
      ) : null}

      <RecentStrip
        recent={recent}
        total={conversationsTotal}
        onSelect={(id) => { setSelectedId(id); setActiveTab('detail') }}
      />

      <MobileNav
        open={navOpen}
        onClose={() => setNavOpen(false)}
        activeTab={activeTab}
        onChange={(tab) => { setActiveTab(tab); setNavOpen(false) }}
      />

      <main className={`workspace workspace-${activeTab}`}>
        <ConversationList
          conversations={filteredConversations}
          selectedId={selectedId}
          onSelect={(id) => { setSelectedId(id); if (window.innerWidth < 900) setActiveTab('detail') }}
          query={query}
          onQueryChange={setQuery}
          total={conversationsTotal}
          hasMore={conversationsHasMore}
          onLoadMore={loadMoreConversations}
          loadingMore={loadingMore}
          active={activeTab === 'inbox'}
          onOpenSettings={() => setSettingsOpen(true)}
          pinned={pinnedItems}
          onTogglePin={togglePin}
        />
        <ConversationDetail
          detail={detail}
          onReply={sendReply}
          onHideMessage={hideMessage}
          onHideLatest={hideLatest}
          sending={sending}
          sendingMeta={sendingMeta}
          uiSettings={settings.web_settings}
          onBack={() => setActiveTab('inbox')}
          active={activeTab === 'detail'}
        />
        <aside className="side-stack">
          <AliasPanel aliases={aliases} onOpenSettings={() => setSettingsOpen(true)} />
        </aside>
      </main>

      <SettingsPanel
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        settings={settings.web_settings}
        channels={settings.channels || []}
        onSave={saveSettings}
        saving={saving}
      />
    </div>
  )
}

export default function App() {
  return (
    <SettingsProvider>
      <AppInner />
    </SettingsProvider>
  )
}
