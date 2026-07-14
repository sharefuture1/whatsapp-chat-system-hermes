import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api, setSessionToken, setUnauthorizedHandler, clearSessionToken } from './api'
import { useAccountsController } from './accounts/useAccountsController'
import { SettingsProvider, useSettings } from './settings'
import { buildContacts, buildInbox, filterInbox } from './inboxModel'
import { contactSelectionPlan, conversationDeletePlan } from './conversationLifecycle'
import { createRefreshCoordinator, mergeConversationPages } from './workspaceRefresh'
import AccountCenterPage from './components/AccountCenterPage'
import BroadcastCenterPage from './components/BroadcastCenterPage'
import ChatList from './components/ChatList'
import ChatPane from './components/ChatPane'
import ContactsPage from './components/ContactsPage'
import DiscoverPage from './components/DiscoverPage'
import LoginScreen from './components/LoginScreen'
import MePage from './components/MePage'
import PluginCenterPage from './components/PluginCenterPage'
import SchedulerCenterPage from './components/SchedulerCenterPage'
import SettingsPanel from './components/SettingsPanel'
import TabBar from './components/TabBar'
import UserManagementPage from './components/UserManagementPage'

const TOKEN_KEY='***'
const USERNAME_KEY='chat-system-username'
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

function deriveAutoTranslateState(settings, apiSettings) {
  const pluginEnabled = settings.plugins ? settings.plugins.auto_translate !== false : true
  const settingEnabled = !!settings.web_settings?.message_ops?.auto_translate
  const aiConfigured = !!apiSettings?.api_key_configured
  const serverState = apiSettings?.auto_translate
  return {
    pluginEnabled: serverState?.plugin_enabled ?? pluginEnabled,
    settingEnabled: serverState?.setting_enabled ?? settingEnabled,
    aiConfigured: serverState?.ai_configured ?? aiConfigured,
    ready: serverState?.ready ?? (pluginEnabled && settingEnabled && aiConfigured),
    blockedReason: serverState?.blocked_reason || (!pluginEnabled ? 'plugin_disabled' : !settingEnabled ? 'setting_disabled' : !aiConfigured ? 'ai_not_configured' : null),
  }
}

function AppInner() {
  const settingsApi = useSettings()
  const { t } = settingsApi
  const [sessionToken, setToken] = useState(() => {
    const stored = localStorage.getItem(TOKEN_KEY) || ''
    setSessionToken(stored)
    return stored
  })
  const USERNAME_KEY = 'chat-system-username'
  const [loginError, setLoginError] = useState('')
  const [loginLoading, setLoginLoading] = useState(false)
  const [loggedInUsername, setLoggedInUsername] = useState(() => localStorage.getItem(USERNAME_KEY) || '')
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
  const [pluginCenterOpen, setPluginCenterOpen] = useState(false)
  const [schedulerCenterOpen, setSchedulerCenterOpen] = useState(false)
  const [broadcastCenterOpen, setBroadcastCenterOpen] = useState(false)
  const [userMgmOpen, setUserMgmOpen] = useState(false)
  const accountsController = useAccountsController(Boolean(sessionToken))
  const accountsRef = useRef([])
  const refreshCoordinatorRef = useRef(createRefreshCoordinator())
  accountsRef.current = accountsController.accounts
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
    localStorage.removeItem(USERNAME_KEY)
    clearSessionToken()
    setToken('')
    setLoggedInUsername('')
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

  const handleLogin = async ({ username, password }) => {
    setLoginLoading(true)
    setLoginError('')
    try {
      const data = await api.post('/login', { username, password })
      localStorage.setItem(TOKEN_KEY, data.session_token)
      localStorage.setItem(USERNAME_KEY, data.username || username)
      setSessionToken(data.session_token)
      setToken(data.session_token)
      setLoggedInUsername(data.username || username)
    } catch (e) {
      setLoginError(e.message)
    } finally {
      setLoginLoading(false)
    }
  }

  const handleRegister = async ({ username, password }) => {
    setLoginLoading(true)
    setLoginError('')
    try {
      await api.post('/v1/users/register', { username, password })
      // Auto-login after successful registration
      await handleLogin({ username, password })
    } catch (e) {
      setLoginError(e.message)
      setLoginLoading(false)
    }
  }

  const fetchConversationsPage = useCallback(async (page) => {
    const standaloneRes = await api.get(`/v1/conversations?platform=all&account_id=all&limit=200`)
    const contactsRes = await api.get('/v1/contacts?platform=all&account_id=all&limit=500')
    const inbox = buildInbox({
      legacy: [],
      standalone: standaloneRes.items || [],
      standaloneAccounts: standaloneRes.available_accounts || accountsRef.current || [],
    })
    return {
      items: inbox.conversations,
      contacts: buildContacts({
        legacy: [],
        standalone: contactsRes.items || [],
        accounts: inbox.accounts,
      }),
      accounts: inbox.accounts,
      legacyTotal: Number(standaloneRes.total) || 0,
      has_more: Boolean(standaloneRes.has_more),
      page,
    }
  }, [])

  const commitConversationsPage = useCallback((snapshot, append = false) => {
    setInboxAccounts(snapshot.accounts)
    setContacts(snapshot.contacts)
    setConversations(current => {
      const merged = mergeConversationPages(current, snapshot.items, append)
      setConversationsTotal(append ? Math.max(snapshot.legacyTotal, merged.length) : merged.length)
      return merged
    })
    setConversationsHasMore(snapshot.has_more)
    setConversationsPage(snapshot.page)
  }, [])

  const refreshWorkspace = useCallback(({ silent = false, fresh = false } = {}) => {
    return refreshCoordinatorRef.current.run(async () => {
      try {
        const [convRes, dashboardRes] = await Promise.all([
          fetchConversationsPage(1),
          api.get('/v1/dashboard'),
        ])
        return { convRes, dashboardRes }
      } catch (e) {
        if (!silent) showError(e)
        return null
      }
    }, result => {
      if (!result) return
      const { convRes, dashboardRes } = result
      const items = convRes.items || []
        if (dashboardRes) setDashboard(dashboardRes)
        commitConversationsPage(convRes)
        setRefreshTick(prev => prev + 1)
        // Sync pinned set from server-side authoritative flag
        setPinned(prev => {
          const next = items.filter(i => i.pinned).map(i => i.conversation_key || i.user_id)
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
          return prev
        })
    }, { fresh })
  }, [commitConversationsPage, fetchConversationsPage])

  const loadMoreConversations = useCallback(async () => {
    if (loadingMore || !conversationsHasMore) return
    setLoadingMore(true)
    try {
      const snapshot = await fetchConversationsPage(conversationsPage + 1)
      commitConversationsPage(snapshot, true)
    } catch (e) {
      showError(e)
    } finally {
      setLoadingMore(false)
    }
  }, [commitConversationsPage, conversationsHasMore, conversationsPage, fetchConversationsPage, loadingMore])

  const refreshSettings = useCallback(async () => {
    const [settingsData, aiData] = await Promise.all([
      api.get('/v1/settings'),
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
  const refreshInterval = autoSeconds > 0 ? Math.max(30, autoSeconds) : 0
  useEffect(() => {
    if (!sessionToken || refreshInterval <= 0) return undefined
    let timer = null
    let stopped = false
    let running = false
    const delay = refreshInterval * 1000
    const clearTimer = () => {
      if (timer) clearTimeout(timer)
      timer = null
    }
    const schedule = (wait = delay) => {
      if (stopped || document.visibilityState !== 'visible') return
      clearTimer()
      timer = setTimeout(run, wait)
    }
    const run = async () => {
      timer = null
      if (stopped || running || document.visibilityState !== 'visible') return
      running = true
      await refreshWorkspace({ silent: true })
      running = false
      schedule()
    }
    const onVisibilityChange = () => {
      if (document.visibilityState === 'visible') schedule(0)
      else clearTimer()
    }
    schedule()
    document.addEventListener('visibilitychange', onVisibilityChange)
    return () => {
      stopped = true
      clearTimer()
      document.removeEventListener('visibilitychange', onVisibilityChange)
    }
  }, [sessionToken, refreshInterval, refreshWorkspace])

  const saveSettings = async (payload, done) => {
    setSaving(true)
    try {
      await api.put('/v1/settings', {
        channels: payload.channels || settings.channels || [],
        web_settings: payload.web_settings || payload,
      })
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

  const sendReply = async (conversation, message, mode, { previewOnly = false, idempotencyKey = null } = {}) => {
    setSending(!previewOnly)
    try {
      if (conversation?.source !== 'standalone' || !conversation?.conversation_id) {
        throw new Error(t('conversationUnavailable') || 'Conversation is not available in Standalone mode')
      }
      const data = await api.post(`/v1/conversations/${encodeURIComponent(conversation.conversation_id)}/reply`, { message, idempotency_key: idempotencyKey, preview_only: previewOnly })
      if (data?.success !== true) {
        const error = new Error(data?.detail || t('sendFailed') || 'Message delivery failed')
        error.code = data?.code || 'delivery_failed'
        error.retryable = data?.retryable !== false
        throw error
      }
      if (!previewOnly) {
        setSendingMeta({ mode: data.mode, language: data.rewrite?.language || 'direct' })
        refreshWorkspace({ silent: true, fresh: true })
      }
      return data
    } catch (e) {
      if (!previewOnly) showError(e)
      throw e
    } finally {
      if (!previewOnly) setSending(false)
    }
  }

  const hideMessage = async (messageId) => {
    try {
      throw new Error(t('messageHideUnavailable') || 'Message hiding is not available in Standalone mode')
    } catch (e) {
      showError(e)
    }
  }

  const togglePin = useCallback(async (conversation) => {
    if (!conversation) return
    const pinKey = conversation.conversation_key || conversation.user_id
    const isPinned = pinned.includes(pinKey) || Boolean(conversation.pinned)
    setPinned(prev => {
      const updated = isPinned ? prev.filter(item => item !== pinKey) : [pinKey, ...prev.filter(item => item !== pinKey)]
      localStorage.setItem(PIN_KEY, JSON.stringify(updated))
      return updated
    })
    try {
      if (conversation.source === 'standalone' && conversation.conversation_id) {
        await api.patch(`/v1/conversations/${encodeURIComponent(conversation.conversation_id)}`, { pinned: !isPinned })
      }
      refreshWorkspace({ silent: true, fresh: true })
    } catch (error) {
      setPinned(prev => {
        const rolledBack = isPinned
          ? [pinKey, ...prev.filter(item => item !== pinKey)]
          : prev.filter(item => item !== pinKey)
        localStorage.setItem(PIN_KEY, JSON.stringify(rolledBack))
        return rolledBack
      })
      showError(error)
    }
  }, [pinned, refreshWorkspace])

  const deleteChat = useCallback(async (conversation) => {
    if (!conversation || !window.confirm(t('deleteConversationConfirm') || '删除此会话？之后可由新消息重新出现。')) return
    const plan = conversationDeletePlan(conversation)
    const wasPinned = pinned.includes(plan.pinKey)
    setPinned(prev => {
      const updated = prev.filter(p => p !== plan.pinKey)
      localStorage.setItem(PIN_KEY, JSON.stringify(updated))
      return updated
    })
    try {
      if (plan.method === 'DELETE') await api.delete(plan.path)
      else await api.post(plan.path, plan.body)
      if (selectedId === plan.conversationKey) {
        setSelectedId('')
        setSelectedName('')
      }
      await refreshWorkspace({ silent: true, fresh: true })
    } catch (e) {
      if (wasPinned) setPinned(prev => prev.includes(plan.pinKey) ? prev : [plan.pinKey, ...prev])
      showError(e)
    }
  }, [pinned, refreshWorkspace, selectedId, t])

  const markRead = useCallback((userId, ts, conversation = null) => {
    if (!userId) return
    const cur = readTime(userId)
    if (ts > cur) {
      writeTime(userId, ts)
      readMapRef.current = { ...(readMapRef.current || {}), [userId]: ts }
      setReadTick(prev => prev + 1)
      if (conversation?.source === 'standalone' && conversation?.conversation_id) {
        api.post(`/v1/conversations/${encodeURIComponent(conversation.conversation_id)}/read`, {}).catch(() => {})
      }
    }
  }, [])

  const selectConversation = useCallback((conversationKey) => {
    setSelectedId(conversationKey)
    const found = conversations.find(c => c.conversation_key === conversationKey)
    if (found) {
      setSelectedName(found.user_name)
      markRead(conversationKey, found.last_timestamp, found)
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
    if (found) markRead(found.conversation_key, found.last_timestamp, found)
  }, [conversations, selectedId, markRead])

  const platformOptions = useMemo(() => {
    const set = new Set((conversations || []).map(item => item.platform).filter(Boolean))
    return ['all', ...Array.from(set)]
  }, [conversations])

  const filteredConversations = useMemo(() => {
    const q = query.trim().toLowerCase()
    const contactProfiles = settings.web_settings?.contact_profiles || {}
    return filterInbox(conversations, { platform: platformFilter, accountId: accountFilter }).filter(item => {
      const remark = String(item.contact_profile?.remark || contactProfiles[item.user_id]?.remark || '').toLowerCase()
      if (!q) return true
      return item.user_name?.toLowerCase().includes(q) ||
        item.user_id?.toLowerCase().includes(q) ||
        item.last_message?.toLowerCase().includes(q) ||
        item.account_name?.toLowerCase().includes(q) ||
        item.account_label?.toLowerCase().includes(q) ||
        remark.includes(q)
    })
  }, [conversations, query, platformFilter, accountFilter, settings.web_settings?.contact_profiles])

  const contactProfileMap = useMemo(
    () => settings.web_settings?.contact_profiles || {},
    [settings.web_settings?.contact_profiles],
  )
  const chatListAccounts = useMemo(
    () => inboxAccounts.filter(account => platformFilter === 'all' || account.platform === platformFilter),
    [inboxAccounts, platformFilter],
  )
  const handlePlatformFilterChange = useCallback(platform => {
    setPlatformFilter(platform)
    setAccountFilter('all')
    setSelectedId('')
    setSelectedName('')
  }, [])
  const handleAccountFilterChange = useCallback(accountId => {
    setAccountFilter(accountId)
    setSelectedId('')
    setSelectedName('')
  }, [])
  const openReplySettings = useCallback(() => {
    setSettingsInitialTab('reply')
    setSettingsOpen(true)
  }, [])
  const handleTabChange = useCallback(tab => {
    setActiveTab(tab)
    if (tab !== 'me') setAccountCenterOpen(false)
  }, [])

  const autoTranslateState = deriveAutoTranslateState(settings, apiSettings)
  const autoTranslate = autoTranslateState.ready
  const selectedConversation = useMemo(() => conversations.find(c => c.conversation_key === selectedId) || null, [conversations, selectedId])
  const selectedAccount = useMemo(
    () => inboxAccounts.find(item => item.id === accountFilter) || null,
    [inboxAccounts, accountFilter],
  )
  const selectedContactProfile = useMemo(() => {
    if (!selectedConversation?.user_id) return null
    return selectedConversation.contact_profile || (settings.web_settings?.contact_profiles || {})[selectedConversation.user_id] || null
  }, [settings.web_settings?.contact_profiles, selectedConversation])
  const selectedUserOverride = useMemo(() => {
    if (!selectedConversation?.user_id) return null
    return selectedConversation.user_override || (settings.web_settings?.reply?.user_overrides || {})[selectedConversation.user_id] || null
  }, [settings.web_settings?.reply?.user_overrides, selectedConversation])

  const quickSaveContactConfig = async (userId, patchFields) => {
    if (!userId) return
    setSaving(true)
    try {
      if (selectedConversation?.source === 'standalone' && selectedConversation?.contact_id) {
        await api.put(`/v1/contacts/${encodeURIComponent(selectedConversation.contact_id)}/settings`, patchFields)
        await refreshWorkspace({ silent: true, fresh: true })
        setBanner(t('saved'))
        return
      }
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
      await api.put('/v1/settings', {
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

  if (!sessionToken) {
    return <LoginScreen onLogin={handleLogin} onRegister={handleRegister} error={loginError} loading={loginLoading} />
  }

  return (
    <div className="wx-shell">
      <div className="wx-shell-content">
        {/* PC sidebar navigation */}
        <nav className="wx-sidebar-nav" aria-label="Main navigation">
          <button type="button" className={`wx-nav-btn ${activeTab === 'chats' ? 'active' : ''}`} onClick={() => { setActiveTab('chats'); setAccountCenterOpen(false) }} title={t('tabChats')}>
            <svg viewBox="0 0 24 24"><path d="M4 5h16a1 1 0 0 1 1 1v11a1 1 0 0 1-1 1h-9l-4 3v-3H4a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1z"/></svg>
            <span className="wx-nav-label">{t('tabChats')}</span>
            {unreadChats > 0 ? <span className="wx-nav-badge">{unreadChats > 99 ? '99+' : unreadChats}</span> : null}
          </button>
          <button type="button" className={`wx-nav-btn ${activeTab === 'contacts' ? 'active' : ''}`} onClick={() => { setActiveTab('contacts'); setAccountCenterOpen(false) }} title={t('tabContacts')}>
            <svg viewBox="0 0 24 24"><circle cx="9" cy="9" r="3"/><path d="M3 19c0-3 3-5 6-5s6 2 6 5"/><circle cx="17" cy="8" r="2.4"/><path d="M14 14c2.5-.7 7 .6 7 4"/></svg>
            <span className="wx-nav-label">{t('tabContacts')}</span>
          </button>
          <button type="button" className={`wx-nav-btn ${activeTab === 'discover' ? 'active' : ''}`} onClick={() => { setActiveTab('discover'); setAccountCenterOpen(false) }} title={t('tabDiscover')}>
            <svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M15 9l-2 6-6 2 2-6z"/></svg>
            <span className="wx-nav-label">{t('tabDiscover')}</span>
          </button>
          <button type="button" className={`wx-nav-btn ${activeTab === 'me' ? 'active' : ''}`} onClick={() => { setActiveTab('me'); setAccountCenterOpen(false) }} title={t('tabMe')}>
            <svg viewBox="0 0 24 24"><circle cx="12" cy="8" r="4"/><path d="M4 20c0-3.5 4-6 8-6s8 2.5 8 6"/></svg>
            <span className="wx-nav-label">{t('tabMe')}</span>
          </button>
        </nav>

        {activeTab === 'chats' && (
          <div className={`wx-chat-layout ${selectedId ? 'mobile-chat-open' : 'mobile-list-open'}`}>
            <ChatList
              conversations={filteredConversations}
              selectedId={selectedId}
              selectedProfileMap={contactProfileMap}
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
              onPlatformFilterChange={handlePlatformFilterChange}
              accounts={chatListAccounts}
              selectedAccountId={accountFilter}
              selectedAccountName={selectedAccount?.name || ''}
              onAccountChange={handleAccountFilterChange}
              onOpenSettings={openReplySettings}
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
              onReply={(target, message, mode, options) => sendReply(selectedConversation, message, mode, options)}
              onHideMessage={hideMessage}
              sending={sending}
              sendingMeta={sendingMeta}
              autoTranslate={autoTranslate}
              autoTranslateState={autoTranslateState}
              uiSettings={settings.web_settings}
              onOpenSettings={() => { setSettingsInitialTab('reply'); setSettingsOpen(true) }}
              onOpenContactConfig={() => { setSettingsInitialTab('reply'); setSettingsOpen(true) }}
              pinned={selectedConversation ? pinnedSet.has(selectedConversation.conversation_key) || Boolean(selectedConversation.pinned) : false}
              onTogglePin={() => selectedConversation && togglePin(selectedConversation)}
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
            onSelect={async (item) => {
              try {
                const plan = contactSelectionPlan(item)
                let conversationKey = plan.conversationKey
                if (plan.ensure) {
                  const ensured = await api.post(plan.ensure.path, plan.ensure.body)
                  await refreshWorkspace({ silent: true, fresh: true })
                  if (item.source === 'standalone' && ensured?.conversation_id) {
                    conversationKey = `standalone:${ensured.conversation_id}`
                  }
                }
                if (conversationKey) selectConversation(conversationKey)
                setActiveTab('chats')
              } catch (e) {
                showError(e)
              }
            }}
          />
        )}

        {activeTab === 'discover' && (
          <DiscoverPage dashboard={dashboard} channels={settings.channels || []} conversations={conversations} />
        )}

        {activeTab === 'me' && !accountCenterOpen && !pluginCenterOpen && !userMgmOpen && (
          <MePage
            health={health}
            onOpenSettings={() => { setSettingsInitialTab('ui'); setSettingsOpen(true) }}
            onOpenGlobalAi={() => { setSettingsInitialTab('ai'); setSettingsOpen(true) }}
            onOpenAccounts={() => setAccountCenterOpen(true)}
            onOpenPlugins={() => setPluginCenterOpen(true)}
            onOpenUserMgm={() => setUserMgmOpen(true)}
            onLogout={logout}
            autoTranslate={autoTranslate}
            accountSummary={accountsController.summary}
            aiSummary={{ configured: !!apiSettings.api_key_configured, model: apiSettings.default_model || settings.web_settings?.reply?.ai_model || '' }}
          />
        )}

        {activeTab === 'me' && pluginCenterOpen && (
          <PluginCenterPage
            onBack={() => setPluginCenterOpen(false)}
            onOpenScheduler={() => setSchedulerCenterOpen(true)}
            onOpenBroadcast={() => setBroadcastCenterOpen(true)}
          />
        )}

        {activeTab === 'me' && userMgmOpen && (
          <UserManagementPage
            onClose={() => setUserMgmOpen(false)}
            onSwitchUser={() => { setUserMgmOpen(false); logout() }}
          />
        )}

        {activeTab === 'me' && schedulerCenterOpen && (
          <SchedulerCenterPage onBack={() => { setSchedulerCenterOpen(false); setPluginCenterOpen(true) }} />
        )}

        {activeTab === 'me' && broadcastCenterOpen && (
          <BroadcastCenterPage onBack={() => { setBroadcastCenterOpen(false); setPluginCenterOpen(true) }} />
        )}

        {activeTab === 'me' && accountCenterOpen && (
          <AccountCenterPage controller={accountsController} onBack={() => setAccountCenterOpen(false)} />
        )}
      </div>

      <TabBar activeTab={activeTab} onChange={handleTabChange} unreadChats={unreadChats} hidden={(activeTab === 'chats' && Boolean(selectedId)) || accountCenterOpen} />

      <SettingsPanel
        open={settingsOpen}
        initialTab={settingsInitialTab}
        selectedConversation={selectedConversation}
        onOpenAccounts={() => { setSettingsOpen(false); setActiveTab('me'); setAccountCenterOpen(true) }}
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
