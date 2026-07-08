import { useCallback, useEffect, useMemo, useState } from 'react'
import { api, setSessionToken, setUnauthorizedHandler, clearSessionToken } from './api'
import { SettingsProvider, useSettings } from './settings'
import ChatList from './components/ChatList'
import ChatPane from './components/ChatPane'
import ContactsPage from './components/ContactsPage'
import DiscoverPage from './components/DiscoverPage'
import LoginScreen from './components/LoginScreen'
import MePage from './components/MePage'
import SettingsPanel from './components/SettingsPanel'
import TabBar from './components/TabBar'

const TOKEN_KEY = 'chat-system-token'
const PAGE_SIZE = 30
const PIN_KEY = 'chat-system-pinned'
const READ_KEY = 'chat-system-read'

function readTime(userId) {
  try {
    const raw = localStorage.getItem(READ_KEY) || '{}'
    const map = JSON.parse(raw)
    return Number(map[userId] || 0)
  } catch { return 0 }
}

function writeTime(userId, ts) {
  try {
    const raw = localStorage.getItem(READ_KEY) || '{}'
    const map = JSON.parse(raw) || {}
    map[userId] = ts
    localStorage.setItem(READ_KEY, JSON.stringify(map))
  } catch {}
}

function AppInner() {
  const settingsApi = useSettings()
  const { t } = settingsApi
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
  const [selectedName, setSelectedName] = useState('')
  const [settings, setSettings] = useState({ channels: [], aliases: {}, web_settings: {} })
  const [saving, setSaving] = useState(false)
  const [sending, setSending] = useState(false)
  const [sendingMeta, setSendingMeta] = useState(null)
  const [query, setQuery] = useState('')
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [activeTab, setActiveTab] = useState('chats')
  const [pinned, setPinned] = useState(() => {
    try { return JSON.parse(localStorage.getItem(PIN_KEY) || '[]') } catch { return [] }
  })
  const [readMap, setReadMap] = useState(() => {
    try { return JSON.parse(localStorage.getItem(READ_KEY) || '{}') } catch { return {} }
  })

  const logout = useCallback(async () => {
    try {
      if (sessionToken) await api.post('/logout', {})
    } catch {}
    localStorage.removeItem(TOKEN_KEY)
    clearSessionToken()
    setToken('')
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
      const items = convRes.items || []
      setDashboard(dashboardRes)
      setConversations(items)
      setConversationsTotal(convRes.total || 0)
      setConversationsHasMore(Boolean(convRes.has_more))
      setConversationsPage(convRes.page || 1)

      setSelectedId(prev => {
        const current = items.find(c => c.user_id === prev)
        if (current) {
          setSelectedName(current.user_name)
          return prev
        }
        const unreadCandidate = items.find(c => {
          const ts = Number(c.last_timestamp || 0)
          const lastRead = readMap[c.user_id] || readTime(c.user_id)
          return ts > lastRead
        })
        const fallback = unreadCandidate || items[0] || null
        if (fallback) {
          setSelectedName(fallback.user_name)
          return fallback.user_id
        }
        setSelectedName('')
        return ''
      })
    } catch (e) {
      if (!silent) showError(e)
    }
  }, [fetchConversationsPage, readMap])

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
      return true
    } catch (e) {
      showError(e)
      return false
    } finally {
      setSending(false)
    }
  }

  const hideMessage = async (messageId) => {
    try {
      await api.post('/messages/hide', { message_ids: [messageId] })
    } catch (e) {
      showError(e)
    }
  }

  const togglePin = useCallback((userId) => {
    setPinned(prev => {
      const next = prev.includes(userId) ? prev.filter(p => p !== userId) : [...prev, userId]
      localStorage.setItem(PIN_KEY, JSON.stringify(next))
      return next
    })
  }, [])

  const markRead = useCallback((userId, ts) => {
    if (!userId) return
    const cur = readTime(userId)
    if (ts > cur) {
      writeTime(userId, ts)
      setReadMap(prev => ({ ...prev, [userId]: ts }))
    }
  }, [])

  const selectConversation = useCallback((userId) => {
    setSelectedId(userId)
    const found = conversations.find(c => c.user_id === userId)
    if (found) {
      setSelectedName(found.user_name)
      markRead(userId, found.last_timestamp)
    } else {
      setSelectedName(userId)
    }
  }, [conversations, markRead])

  const nextConversation = useCallback(() => {
    if (!conversations.length) return
    if (!selectedId) {
      const first = conversations[0]
      if (first) selectConversation(first.user_id)
      return
    }
    const idx = conversations.findIndex(c => c.user_id === selectedId)
    const next = conversations[(idx + 1 + conversations.length) % conversations.length]
    if (next) selectConversation(next.user_id)
  }, [conversations, selectedId, selectConversation])

  useEffect(() => {
    if (!selectedId) return
    const found = conversations.find(c => c.user_id === selectedId)
    if (found) markRead(found.user_id, found.last_timestamp)
  }, [conversations, selectedId, markRead])

  const filteredConversations = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return conversations
    return conversations.filter(item =>
      item.user_name?.toLowerCase().includes(q) ||
      item.user_id?.toLowerCase().includes(q) ||
      item.last_message?.toLowerCase().includes(q)
    )
  }, [conversations, query])

  const unread = useMemo(() => {
    const out = {}
    for (const c of conversations) {
      const ts = Number(c.last_timestamp || 0)
      const lastRead = readMap[c.user_id] || readTime(c.user_id)
      if (ts > lastRead) out[c.user_id] = 1
    }
    return out
  }, [conversations, readMap])

  const unreadChats = useMemo(() => Object.values(unread).reduce((a, b) => a + b, 0), [unread])
  const pinnedItems = useMemo(() => {
    const map = new Map(conversations.map(c => [c.user_id, c]))
    return pinned.map(id => map.get(id)).filter(Boolean)
  }, [pinned, conversations])

  if (!sessionToken) {
    return <LoginScreen onLogin={handleLogin} error={loginError} loading={loginLoading} />
  }

  const autoTranslate = !!settings.web_settings?.message_ops?.auto_translate

  return (
    <div className="wx-shell">
      <div className="wx-shell-content">
        {activeTab === 'chats' && (
          <div className="wx-chat-layout">
            <ChatList
              conversations={filteredConversations}
              selectedId={selectedId}
              onSelect={selectConversation}
              query={query}
              onQueryChange={setQuery}
              total={conversationsTotal}
              hasMore={conversationsHasMore}
              onLoadMore={loadMoreConversations}
              loadingMore={loadingMore}
              pinned={pinnedItems}
              onTogglePin={togglePin}
              onOpenSettings={() => setSettingsOpen(true)}
              onChangeLanguage={settingsApi.setLanguage}
              onToggleTheme={settingsApi.toggleTheme}
              language={settingsApi.language}
              languages={settingsApi.languages}
              theme={settingsApi.theme}
              onLogout={logout}
              unread={unread}
              autoTranslate={autoTranslate}
            />
            <ChatPane
              userId={selectedId}
              userName={selectedName}
              onBack={() => {}}
              onReply={sendReply}
              onHideMessage={hideMessage}
              sending={sending}
              sendingMeta={sendingMeta}
              uiSettings={settings.web_settings}
              onOpenSettings={() => setSettingsOpen(true)}
              onTogglePin={togglePin}
              pinned={pinned}
              active
              health={health}
              onNextConversation={nextConversation}
            />
          </div>
        )}

        {activeTab === 'contacts' && (
          <ContactsPage conversations={conversations} onSelect={(id) => { selectConversation(id); setActiveTab('chats') }} />
        )}

        {activeTab === 'discover' && (
          <DiscoverPage dashboard={dashboard} channels={settings.channels || []} />
        )}

        {activeTab === 'me' && (
          <MePage
            health={health}
            onOpenSettings={() => setSettingsOpen(true)}
            onLogout={logout}
            profilePath={settings.profile}
            autoTranslate={autoTranslate}
          />
        )}
      </div>

      <TabBar activeTab={activeTab} onChange={setActiveTab} unreadChats={unreadChats} />

      <SettingsPanel
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        settings={settings.web_settings}
        channels={settings.channels || []}
        onSave={saveSettings}
        saving={saving}
      />

      {banner ? <div className="wx-toast">{banner}</div> : null}
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
