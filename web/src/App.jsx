import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api, setSessionToken, setUnauthorizedHandler, clearSessionToken } from './api'
import { useAccountsController } from './accounts/useAccountsController'
import { SettingsProvider, useSettings } from './settings'
import { buildContacts, buildInbox, filterInbox } from './inboxModel'
import AccountCenterPage from './components/AccountCenterPage'
import ChatList from './components/ChatList'
import ChatPane from './components/ChatPane'
import ContactsPage from './components/ContactsPage'
import DiscoverPage from './components/DiscoverPage'
import LoginScreen from './components/LoginScreen'
import MePage from './components/MePage'
import SettingsPanel from './components/SettingsPanel'
import TabBar from './components/TabBar'

const TOKEN_KEY='***'
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
  const [contacts, setContacts] = useState([])
  const [inboxAccounts, setInboxAccounts] = useState([])
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
  const [refreshTick, setRefreshTick] = useState(0)
  const [query, setQuery] = useState('')
  const [platformFilter, setPlatformFilter] = useState('all')
  const [accountFilter, setAccountFilter] = useState('all')
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [settingsInitialTab, setSettingsInitialTab] = useState('reply')
  const [activeTab, setActiveTab] = useState('chats')
  const [accountCenterOpen, setAccountCenterOpen] = useState(false)
  const accountsController = useAccountsController(Boolean(sessionToken))
  const [pinned, setPinned] = useState(() => {
    try { return JSON.parse(localStorage.getItem(PIN_KEY) || '[]') } catch { return [] }
  })
  const readMapRef = useRef(null)
  if (readMapRef.current === null) {
    try { readMapRef.current = JSON.parse(localStorage.getItem(READ_KEY) || '{}') } catch { readMapRef.current = {} }
  }
  const [readTick, setReadTick] = useState(0)

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
    const [legacyRes, standaloneRes, contactsRes] = await Promise.all([
      api.get(`/conversations?page=${page}&page_size=${PAGE_SIZE}`),
      api.get(`/v1/conversations?platform=all&account_id=all&limit=200`),
      api.get('/v1/contacts?platform=all&account_id=all&limit=500'),
    ])
    const inbox = buildInbox({
      legacy: legacyRes.items || [],
      standalone: standaloneRes.items || [],
      standaloneAccounts: standaloneRes.available_accounts || accountsController.accounts || [],
    })
    const nextItems = inbox.conversations
    const nextContacts = buildContacts({
      legacy: legacyRes.items || [],
      standalone: contactsRes.items || [],
      accounts: inbox.accounts,
    })
    setInboxAccounts(inbox.accounts)
    setContacts(nextContacts)
    setConversations(nextItems)
    setConversationsTotal(nextItems.length)
    setConversationsHasMore(Boolean(legacyRes.has_more))
    setConversationsPage(page)
    return { items: nextItems, total: nextItems.length, has_more: Boolean(legacyRes.has_more), page }
  }, [accountsController.accounts])

  const refreshWorkspace = useCallback(async ({ silent = false } = {}) => {
    try {
      const convRes = await fetchConversationsPage(1, false)
      const dashboardRes = await api.get('/dashboard')
      const items = convRes.items || []
      setDashboard(dashboardRes)
      setConversations(items)
      setConversationsTotal(convRes.total || 0)
      setConversationsHasMore(Boolean(convRes.has_more))
      setConversationsPage(convRes.page || 1)
      setRefreshTick(prev => prev + 1)
      // Sync pinned set from server-side authoritative flag
      setPinned(prev => {
        const next = items.filter(i => i.pinned).map(i => i.user_id)
        if (next.length === prev.length && next.every((id, idx) => prev[idx] === id)) return prev
        localStorage.setItem(PIN_KEY, JSON.stringify(next))
        return next
      })

      setSelectedId(prev => {
        if (!prev) {
          setSelectedName('')
          return ''
        }
        const current = items.find(c => c.conversation_key === prev)
        if (current) {
          setSelectedName(current.user_name)
          return prev
        }
        setSelectedName('')
        return ''
      })
    } catch (e) {
      if (!silent) showError(e)
    }
  }, [fetchConversationsPage])

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
    const [settingsData, aiData] = await Promise.all([
      api.get('/settings'),
      api.get('/v1/ai/settings').catch(() => ({})),
    ])
    setSettings(settingsData)
    setApiSettings(aiData)
  }, [])

  const [apiSettings, setApiSettings] = useState({})

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

  const saveAiSettings = async ({ base_url, default_model, api_key }) => {
    await api.put('/v1/ai/settings', { base_url, default_model, api_key })
    // 重新加载 AI 设置到本地 state
    const fresh = await api.get('/v1/ai/settings')
    setApiSettings(fresh)
  }

  const sendReply = async (target, message, mode) => {
    setSending(true)
    try {
      const data = await api.post('/reply', { target, message, mode, preview_only: false })
      if (data?.success !== true) {
        const error = new Error(data?.detail || t('sendFailed') || 'Message delivery failed')
        error.code = data?.code || 'delivery_failed'
        error.retryable = data?.retryable !== false
        throw error
      }
      setSendingMeta({ mode: data.mode, language: data.rewrite?.language || 'direct' })
      refreshWorkspace({ silent: true })
      return data
    } catch (e) {
      showError(e)
      throw e
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

  const togglePin = useCallback(async (userId) => {
    const isPinned = pinned.includes(userId)
    setPinned(prev => {
      const updated = isPinned ? prev.filter(p => p !== userId) : [userId, ...prev.filter(p => p !== userId)]
      localStorage.setItem(PIN_KEY, JSON.stringify(updated))
      return updated
    })
    try {
      await api.post('/chat/pin', { user_id: userId, pinned: !isPinned })
      refreshWorkspace({ silent: true })
    } catch {}
  }, [pinned, refreshWorkspace])

  const deleteChat = useCallback(async (userId) => {
    if (!window.confirm(t('deleteConversationConfirm') || '删除此会话？之后可由新消息重新出现。')) return
    const wasPinned = pinned.includes(userId)
    setPinned(prev => {
      const updated = prev.filter(p => p !== userId)
      localStorage.setItem(PIN_KEY, JSON.stringify(updated))
      return updated
    })
    try {
      await api.post('/chat/delete', { user_id: userId })
      if (selectedId === userId) {
        setSelectedId('')
        setSelectedName('')
      }
      await refreshWorkspace({ silent: true })
    } catch (e) {
      if (wasPinned) setPinned(prev => prev.includes(userId) ? prev : [userId, ...prev])
      showError(e)
    }
  }, [pinned, refreshWorkspace, selectedId, t])

  const markRead = useCallback((userId, ts) => {
    if (!userId) return
    const cur = readTime(userId)
    if (ts > cur) {
      writeTime(userId, ts)
      readMapRef.current = { ...(readMapRef.current || {}), [userId]: ts }
      setReadTick(prev => prev + 1)
    }
  }, [])

  const selectConversation = useCallback((conversationKey) => {
    setSelectedId(conversationKey)
    const found = conversations.find(c => c.conversation_key === conversationKey)
    if (found) {
      setSelectedName(found.user_name)
      markRead(conversationKey, found.last_timestamp)
    } else {
      setSelectedName(conversationKey)
    }
  }, [conversations, markRead])

  const unread = useMemo(() => {
    const out = {}
    const readMap = readMapRef.current || {}
    for (const c of conversations) {
      const ts = Number(c.last_timestamp || 0)
      const key = c.conversation_key || c.user_id
      const lastRead = readMap[key] || readTime(key)
      if (ts > lastRead) out[key] = Number(c.unread_count || 1)
    }
    return out
  }, [conversations, readTick])

  const unreadChats = useMemo(() => Object.values(unread).reduce((a, b) => a + b, 0), [unread])
  const pinnedSet = useMemo(() => new Set(pinned), [pinned])

  useEffect(() => {
    if (!selectedId) return
    const found = conversations.find(c => c.conversation_key === selectedId)
    if (found) markRead(found.conversation_key, found.last_timestamp)
  }, [conversations, selectedId, markRead])

  const platformOptions = useMemo(() => {
    const set = new Set((conversations || []).map(item => item.platform).filter(Boolean))
    return ['all', ...Array.from(set)]
  }, [conversations])

  const filteredConversations = useMemo(() => {
    const q = query.trim().toLowerCase()
    const contactProfiles = settings.web_settings?.contact_profiles || {}
    return filterInbox(conversations, { platform: platformFilter, accountId: accountFilter }).filter(item => {
      const remark = String(contactProfiles[item.user_id]?.remark || '').toLowerCase()
      if (!q) return true
      return item.user_name?.toLowerCase().includes(q) ||
        item.user_id?.toLowerCase().includes(q) ||
        item.last_message?.toLowerCase().includes(q) ||
        item.account_name?.toLowerCase().includes(q) ||
        item.account_label?.toLowerCase().includes(q) ||
        remark.includes(q)
    })
  }, [conversations, query, platformFilter, accountFilter, settings.web_settings?.contact_profiles])

  if (!sessionToken) {
    return <LoginScreen onLogin={handleLogin} error={loginError} loading={loginLoading} />
  }

  const autoTranslate = (() => {
    const pluginOn = settings.plugins ? (settings.plugins.auto_translate !== false) : true
    if (!pluginOn) return false
    return !!settings.web_settings?.message_ops?.auto_translate
  })()
  const selectedConversation = useMemo(() => conversations.find(c => c.conversation_key === selectedId) || null, [conversations, selectedId])
  const selectedAccount = useMemo(
    () => inboxAccounts.find(item => item.id === accountFilter) || null,
    [inboxAccounts, accountFilter],
  )
  const selectedContactProfile = useMemo(() => {
    if (!selectedConversation?.user_id) return null
    return (settings.web_settings?.contact_profiles || {})[selectedConversation.user_id] || null
  }, [settings.web_settings?.contact_profiles, selectedConversation])
  const selectedUserOverride = useMemo(() => {
    if (!selectedConversation?.user_id) return null
    return (settings.web_settings?.reply?.user_overrides || {})[selectedConversation.user_id] || null
  }, [settings.web_settings?.reply?.user_overrides, selectedConversation])

  const quickSaveContactConfig = async (userId, patchFields) => {
    if (!userId) return
    setSaving(true)
    try {
      const currentOverrides = settings.web_settings?.reply?.user_overrides || {}
      const currentProfiles = settings.web_settings?.contact_profiles || {}
      const existing = currentOverrides[userId] || {}
      const existingProfile = currentProfiles[userId] || {}
      const nextEntry = {
        ai_model: String(patchFields.ai_model ?? existing.ai_model ?? '').trim(),
        custom_system_prompt: String(patchFields.custom_system_prompt ?? existing.custom_system_prompt ?? '').trim(),
        reply_style: String(patchFields.reply_style ?? existing.reply_style ?? '').trim(),
      }
      const nextProfile = {
        remark: String(patchFields.remark ?? existingProfile.remark ?? '').trim(),
        notes: String(patchFields.notes ?? existingProfile.notes ?? '').trim(),
      }
      await api.put('/settings', {
        channels: settings.channels || [],
        web_settings: {
          ...settings.web_settings,
          contact_profiles: {
            ...currentProfiles,
            [userId]: nextProfile,
          },
          reply: {
            ...(settings.web_settings?.reply || {}),
            user_overrides: {
              ...currentOverrides,
              [userId]: nextEntry,
            },
          },
        },
      })
      await refreshSettings()
      setBanner(t('saved'))
    } catch (e) {
      showError(e)
      throw e
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="wx-shell">
      <div className="wx-shell-content">
        {activeTab === 'chats' && (
          <div className={`wx-chat-layout ${selectedId ? 'mobile-chat-open' : 'mobile-list-open'}`}>
            <ChatList
              conversations={filteredConversations}
              selectedId={selectedId}
              selectedProfileMap={settings.web_settings?.contact_profiles || {}}
              onSelect={selectConversation}
              query={query}
              onQueryChange={setQuery}
              total={conversationsTotal}
              hasMore={conversationsHasMore}
              onLoadMore={loadMoreConversations}
              loadingMore={loadingMore}
              pinned={pinnedSet}
              onTogglePin={togglePin}
              onDeleteChat={deleteChat}
              unread={unread}
              autoTranslate={autoTranslate}
              platformFilter={platformFilter}
              platformOptions={platformOptions}
              onPlatformFilterChange={platform => {
                setPlatformFilter(platform)
                setAccountFilter('all')
                setSelectedId('')
                setSelectedName('')
              }}
              accounts={inboxAccounts.filter(account => platformFilter === 'all' || account.platform === platformFilter)}
              selectedAccountId={accountFilter}
              selectedAccountName={selectedAccount?.name || ''}
              onAccountChange={accountId => {
                setAccountFilter(accountId)
                setSelectedId('')
                setSelectedName('')
              }}
              onOpenSettings={() => { setSettingsInitialTab('reply'); setSettingsOpen(true) }}
            />
            <ChatPane
              userId={selectedConversation?.user_id || ''}
              conversationId={selectedConversation?.conversation_id || ''}
              standalone={selectedConversation?.source === 'standalone'}
              accountLabel={selectedConversation?.account_label || ''}
              accountName={selectedConversation?.account_name || ''}
              platform={selectedConversation?.platform || ''}
              userName={selectedName}
              contactProfile={selectedContactProfile}
              userOverride={selectedUserOverride}
              defaultReplyStyle={settings.web_settings?.reply?.default_reply_style || ''}
              defaultAiModel={settings.web_settings?.reply?.ai_model || settings.model?.default || ''}
              onSaveContactConfig={quickSaveContactConfig}
              onBack={() => { setSelectedId(''); setSelectedName('') }}
              onReply={sendReply}
              onHideMessage={hideMessage}
              sending={sending}
              sendingMeta={sendingMeta}
              uiSettings={settings.web_settings}
              onOpenSettings={() => { setSettingsInitialTab('reply'); setSettingsOpen(true) }}
              onOpenContactConfig={() => { setSettingsInitialTab('reply'); setSettingsOpen(true) }}
              active
              health={health}
              refreshTick={refreshTick}
            />
          </div>
        )}

        {activeTab === 'contacts' && (
          <ContactsPage
            contacts={contacts}
            accounts={inboxAccounts}
            onSelect={(item) => {
              const conversation = conversations.find(c => c.conversation_key === item.conversation_key)
              if (conversation) selectConversation(conversation.conversation_key)
              setActiveTab('chats')
            }}
          />
        )}

        {activeTab === 'discover' && (
          <DiscoverPage dashboard={dashboard} channels={settings.channels || []} conversations={conversations} />
        )}

        {activeTab === 'me' && !accountCenterOpen && (
          <MePage
            health={health}
            onOpenSettings={() => { setSettingsInitialTab('reply'); setSettingsOpen(true) }}
            onOpenAccounts={() => setAccountCenterOpen(true)}
            onLogout={logout}
            autoTranslate={autoTranslate}
            accountSummary={accountsController.summary}
          />
        )}

        {activeTab === 'me' && accountCenterOpen && (
          <AccountCenterPage controller={accountsController} onBack={() => setAccountCenterOpen(false)} />
        )}
      </div>

      <TabBar activeTab={activeTab} onChange={tab => { setActiveTab(tab); if (tab !== 'me') setAccountCenterOpen(false) }} unreadChats={unreadChats} hidden={(activeTab === 'chats' && Boolean(selectedId)) || accountCenterOpen} />

      <SettingsPanel
        open={settingsOpen}
        initialTab={settingsInitialTab}
        selectedConversation={selectedConversation}
        onClose={() => setSettingsOpen(false)}
        settings={settings.web_settings}
        channels={settings.channels || []}
        onSave={saveSettings}
        saving={saving}
        modelDefault={settings.model?.default || ''}
        apiSettings={apiSettings}
        onSaveAiSettings={saveAiSettings}
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