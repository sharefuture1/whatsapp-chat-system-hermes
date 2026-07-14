import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api'
import { fetchPersonaCatalog, assignPersona as assignPersonaApi } from '../personas'
import {
  loadConversationCache,
  saveConversationCache,
  loadTranslationCache,
  saveTranslationCache,
  isConversationCacheFresh,
} from '../chatCache'
import { useSettings } from '../settings'
import { fmtClock } from '../format'
import { formatChatDay, localDayKey } from '../dateTime'
import {
  commitMessagesUpdate,
  createConversationDeltaScheduler,
  createConversationRequestTracker,
  mergeFreshMessages,
  mergeNewMessagesWithStats,
  isTranslationRetryEligible,
  nextTranslationRetryDelay,
} from '../chatSync'

const QUICK_EMOJIS = ['😊', '😂', '🥺', '❤️', '👍', '🙏', '😌', '😉']

function initials(name) {
  if (!name) return '?'
  const trimmed = name.trim()
  if (!trimmed) return '?'
  const parts = trimmed.split(/\s+/).filter(Boolean)
  if (parts.length === 1) return parts[0].slice(0, 2)
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase()
}

function mediaUrl(metadata = {}) {
  return metadata.url || metadata.media_url || metadata.thumbnail_url || null
}

function MessageMedia({ message }) {
  const type = String(message.message_type || '').toLowerCase()
  const url = mediaUrl(message.media_metadata)
  if (!url || !['image', 'video'].includes(type)) return null
  if (type === 'image') return <img className="wx-message-media" src={url} alt="" loading="lazy" />
  return <video className="wx-message-media" src={url} controls preload="metadata" />
}

function avatarColor(name) {
  const colors = ['#5b8def', '#07c160', '#fa9d3b', '#f44c4c', '#9b59b6', '#16a085', '#e67e22', '#2ecc71']
  let h = 0
  for (const ch of name || '') h = (h * 31 + ch.charCodeAt(0)) >>> 0
  return colors[h % colors.length]
}

function dayKey(ts) {
  return localDayKey(ts)
}

function formatDay(ts, t) {
  return formatChatDay(ts, t)
}

function normalizeRewriteLanguage(language) {
  return !language || language === 'direct' ? 'Chinese' : language
}

function maxMessageId(items) {
  return items.reduce((max, item) => {
    const id = Number(item.message_id)
    return Number.isFinite(id) && id > max ? id : max
  }, 0)
}

function nextMessageInGrouped(items, index) {
  for (let i = index + 1; i < items.length; i += 1) {
    if (items[i]?.type === 'msg') return items[i]
  }
  return null
}

function shouldShowBubbleTime(item, nextItem) {
  if (!nextItem) return true
  if (nextItem.role !== item.role) return true
  const delta = Math.abs(Number(nextItem.timestamp || 0) - Number(item.timestamp || 0))
  return delta > 300
}

export default function ChatPane({
  userId,
  conversationId,
  standalone = false,
  accountLabel = '',
  accountName = '',
  platform = '',
  userName,
  contactProfile,
  userOverride,
  defaultReplyStyle,
  defaultAiModel,
  onSaveContactConfig,
  onBack,
  onReply,
  onHideMessage,
  sending,
  sendingMeta,
  autoTranslate = false,
  autoTranslateState = {},
  uiSettings,
  onOpenSettings,
  onOpenContactConfig,
  pinned = false,
  onTogglePin,
  active,
  health,
  refreshTick,
}) {
  const { t } = useSettings()
  const [pageSize] = useState(80)
  const [page, setPage] = useState(1)
  const [messages, setMessages] = useState([])
  const [hasMore, setHasMore] = useState(false)
  const [total, setTotal] = useState(0)
  const [hiddenCount, setHiddenCount] = useState(0)
  const [loadingMore, setLoadingMore] = useState(false)
  const [initialLoading, setInitialLoading] = useState(false)
  const [composer, setComposer] = useState('')
  const [mode, setMode] = useState('smart')
  const [preview, setPreview] = useState(null)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [previewError, setPreviewError] = useState(false)
  const [contactDrawerOpen, setContactDrawerOpen] = useState(false)
  const [contactDrawerTab, setContactDrawerTab] = useState('profile')
  const [contactDraft, setContactDraft] = useState({ remark: '', notes: '', ai_model: '', custom_system_prompt: '', reply_style: '' })
  const [contactSaving, setContactSaving] = useState(false)
  const [contactSaved, setContactSaved] = useState(false)
  const [activeMessageId, setActiveMessageId] = useState(null)
  const [hiddenTranslations, setHiddenTranslations] = useState({})
  const [translationError, setTranslationError] = useState('')
  const scrollRef = useRef(null)
  const lastBottomRef = useRef(true)
  const fetchedFor = useRef(null)
  const requestTracker = useRef(createConversationRequestTracker())
  const deltaScheduler = useRef(createConversationDeltaScheduler())
  const deltaCursorRef = useRef(0)
  const standaloneCursorRef = useRef(null)
  const translatingIdsRef = useRef(new Set())
  const translationWorkerRunningRef = useRef(false)
  const translationGenerationRef = useRef(0)
  const translationAbortRef = useRef(null)
  const translationRetryTimerRef = useRef(null)
  const messagesRef = useRef([])
  const translationQueueVersionRef = useRef(0)
  const [translationWorkerTick, setTranslationWorkerTick] = useState(0)
  const composerRef = useRef(null)
  const [newMessageCount, setNewMessageCount] = useState(0)
  const [toolsOpen, setToolsOpen] = useState(false)
  const [headerMenuOpen, setHeaderMenuOpen] = useState(false)
  const [personaPickerOpen, setPersonaPickerOpen] = useState(false)
  const [personaCatalog, setPersonaCatalog] = useState({ items: [], available: false })
  const [personaLoading, setPersonaLoading] = useState(false)
  const [personaError, setPersonaError] = useState('')
  const [personaSaving, setPersonaSaving] = useState(false)
  const [currentPersona, setCurrentPersona] = useState(null)
  const [hideOwnMessages, setHideOwnMessages] = useState(false)
  const defaultMode = uiSettings?.reply?.default_mode || 'smart'
  const conversationKey = standalone && conversationId ? `standalone:${conversationId}` : `legacy:${userId}`
  useEffect(() => {
    messagesRef.current = messages
  }, [messages])
  const translationQueueVersion = messages.reduce((version, message) => {
    if (message.hidden || message.pending || message.failed || String(message.message_id || '').startsWith('tmp-') || message.translated || !message.content || message.lang === 'Chinese') return version
    return `${version}|${message.message_id}`
  }, '')
  if (translationQueueVersionRef.current !== translationQueueVersion) translationQueueVersionRef.current = translationQueueVersion

  useEffect(() => {
    if (mode === 'direct') {
      setPreview({ mode: 'direct', language: 'direct', message: composer, used_fallback: false })
      setPreviewError(false)
      setPreviewLoading(false)
      return
    }
    setPreview(null)
    setPreviewError(false)
    setPreviewLoading(false)
  }, [composer, mode])

  useEffect(() => {
    setContactDraft({
      remark: contactProfile?.remark || '',
      notes: contactProfile?.notes || '',
      ai_model: userOverride?.ai_model || '',
      custom_system_prompt: userOverride?.custom_system_prompt || '',
      reply_style: userOverride?.reply_style || '',
    })
    setContactDrawerOpen(false)
    setContactDrawerTab('profile')
    setContactSaving(false)
    setContactSaved(false)
  }, [userId, userOverride, contactProfile])

  const fetchPage = async (targetUserId, p, appendOlder = false) => {
    if (!targetUserId) return null
    const request = requestTracker.current.begin(targetUserId)
    const cursor = standalone && appendOlder ? standaloneCursorRef.current : null
    const cursorQuery = cursor
      ? `&before_occurred_at=${encodeURIComponent(cursor.before_occurred_at)}&before_id=${encodeURIComponent(cursor.before_id)}`
      : ''
    const endpoint = conversationId
      ? `/v1/conversations/${encodeURIComponent(conversationId)}/messages?limit=${pageSize}${cursorQuery}`
      : null
    if (!endpoint) throw new Error('Conversation is not available in Standalone mode')
    const cached = loadConversationCache(conversationId)
    const cachedMessages = cached?.messages || []
    if (cachedMessages.length && !appendOlder) {
      setMessages(cachedMessages)
      messagesRef.current = cachedMessages
      setTotal(cached.total_messages || cachedMessages.length)
      setInitialLoading(false)
    }
    if (cachedMessages.length && isConversationCacheFresh(cached) && !appendOlder) {
      fetchedFor.current = targetUserId
      return { messages: cachedMessages, total_messages: cached.total_messages || cachedMessages.length, has_more: cached.has_more, next_cursor: cached.next_cursor }
    }
    const res = await api.get(endpoint)
    if (!requestTracker.current.isCurrent(request, targetUserId)) return null
    const items = standalone ? (res.messages || []).slice() : (res.messages || []).slice().reverse()
    if (appendOlder) {
      setMessages(prev => [...items, ...prev])
    } else {
      setMessages(prev => mergeFreshMessages(items, prev))
    }
    if (standalone) standaloneCursorRef.current = res.next_cursor || null
    saveConversationCache(conversationId, items, {
      total_messages: res.total_messages,
      has_more: res.has_more,
      next_cursor: res.next_cursor,
    })
    setHasMore(Boolean(res.has_more))
    setTotal(res.total_messages || 0)
    setHiddenCount(res.hidden_message_count || 0)
    setPage(p)
    fetchedFor.current = targetUserId
    deltaCursorRef.current = Math.max(deltaCursorRef.current, maxMessageId(items))
    return res
  }

  useEffect(() => {
    if (!userId) {
      requestTracker.current.invalidate()
      fetchedFor.current = null
      return
    }
    const targetUserId = userId
    translationGenerationRef.current += 1
    translationAbortRef.current?.abort()
    translationAbortRef.current = null
    translatingIdsRef.current.clear()
    requestTracker.current.activate(targetUserId)
    deltaScheduler.current.activate(targetUserId)
    setMessages([])
    setHasMore(false)
    setTotal(0)
    setHiddenCount(0)
    setPage(1)
    fetchedFor.current = null
    deltaCursorRef.current = 0
    standaloneCursorRef.current = null
    setNewMessageCount(0)
    setMode(defaultMode)
    setToolsOpen(false)
    setHeaderMenuOpen(false)
    setPersonaPickerOpen(false)
    setCurrentPersona(null)
    setComposer('')
    setPreview(null)
    setPreviewError(false)
    setActiveMessageId(null)
    setHiddenTranslations({})
    setTranslationError('')
    setInitialLoading(true)
    fetchPage(targetUserId, 1, false)
      .then(res => { if (res) lastBottomRef.current = true })
      .catch(() => {})
      .finally(() => {
        if (requestTracker.current.isActive(targetUserId)) setInitialLoading(false)
      })
    return () => {
      translationGenerationRef.current += 1
      translationAbortRef.current?.abort()
      translationAbortRef.current = null
      requestTracker.current.invalidate()
      deltaScheduler.current.invalidate()
    }
  }, [conversationKey, defaultMode, pageSize])

  useEffect(() => {
    if (!userId || !refreshTick || fetchedFor.current !== userId) return
    const targetUserId = userId
    if (conversationId) {
      const wasAtBottom = lastBottomRef.current
      fetchPage(targetUserId, 1, false).then(res => {
        if (res && wasAtBottom) lastBottomRef.current = true
      }).catch(() => {})
      return
    }
    // Standalone mode is the only supported runtime. No legacy delta endpoint.
    // A conversation without a V1 conversation_id cannot be synchronized.
  }, [refreshTick, userId, conversationId])

  const loadMore = async () => {
    if (loadingMore || !hasMore || !userId) return
    setLoadingMore(true)
    try {
      const next = page + 1
      const container = scrollRef.current
      const prevHeight = container ? container.scrollHeight : 0
      await fetchPage(userId, next, true)
      requestAnimationFrame(() => {
        if (container) {
          const newHeight = container.scrollHeight
          container.scrollTop = newHeight - prevHeight
        }
      })
    } catch {} finally {
      setLoadingMore(false)
    }
  }

  useLayoutEffect(() => {
    if (!scrollRef.current) return
    if (lastBottomRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [messages.length, messages[messages.length - 1]?.message_id, messages[messages.length - 1]?.timestamp])

  const onScroll = () => {
    const el = scrollRef.current
    if (!el) return
    const distFromTop = el.scrollTop
    const distFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight
    if (distFromTop < 60 && hasMore && !loadingMore && messages.length > 0) loadMore()
    lastBottomRef.current = distFromBottom < 80
    if (lastBottomRef.current && newMessageCount) setNewMessageCount(0)
  }

  const translateOne = async (msg, generation, signal) => {
    const translationId = String(msg?.message_id || '')
    if (!translationId || translationId.startsWith('tmp-') || msg.pending || msg.failed || msg.translated || msg.lang === 'Chinese' || !isTranslationRetryEligible(msg) || translatingIdsRef.current.has(translationId)) return false
    translatingIdsRef.current.add(translationId)
    const cachedTranslation = loadTranslationCache(msg.message_id, msg.content)
    if (cachedTranslation) {
      commitMessagesUpdate(messagesRef, setMessages, prev => prev.map(item => item.message_id === msg.message_id ? { ...item, ...cachedTranslation } : item))
      translatingIdsRef.current.delete(translationId)
      return true
    }
    try {
      const res = await api.post(`/v1/messages/${msg.message_id}/translate`, { user_id: userId, content: msg.content }, { signal })
      if (generation !== translationGenerationRef.current || signal.aborted) return false
      if (res?.success === false || !res?.translated) {
        const code = res?.error?.code || 'translation_failed'
        setTranslationError(code === 'configuration_error' ? t('translationAiNotConfigured') : t('translationFailed'))
        commitMessagesUpdate(messagesRef, setMessages, prev => prev.map(m => m.message_id === msg.message_id ? { ...m, translationRetryAfter: Date.now() + 30_000 } : m))
        return false
      }
      setTranslationError('')
      const translation = { translated: res.translated, lang: res.lang || msg.lang, translationRetryAfter: undefined }
      saveTranslationCache(msg.message_id, msg.content, translation)
      setMessages(prev => prev.map(m => m.message_id === msg.message_id ? { ...m, ...translation } : m))
      return true
    } catch (error) {
      if (signal.aborted || generation !== translationGenerationRef.current) return false
      const code = error?.data?.detail?.code || error?.data?.code || error?.code
      setTranslationError(code === 'auto_translate_disabled' ? t('translationDisabled') : t('translationFailed'))
      commitMessagesUpdate(messagesRef, setMessages, prev => prev.map(m => m.message_id === msg.message_id ? { ...m, translationRetryAfter: Date.now() + 30_000 } : m))
      return false
    } finally {
      translatingIdsRef.current.delete(translationId)
    }
  }

  useEffect(() => {
    if (!autoTranslate) {
      translationGenerationRef.current += 1
      translationAbortRef.current?.abort()
      translationAbortRef.current = null
    }
  }, [autoTranslate])

  useEffect(() => {
    if (!autoTranslate || !userId || translationWorkerRunningRef.current) return
    const generation = translationGenerationRef.current
    const controller = new AbortController()
    const attempted = new Set()
    translationAbortRef.current = controller
    translationWorkerRunningRef.current = true
    ;(async () => {
      let processed = 0
      while (!controller.signal.aborted && generation === translationGenerationRef.current && processed < 6) {
        const msg = messagesRef.current.find(m => !m.hidden && !m.pending && !m.failed && !String(m.message_id || '').startsWith('tmp-') && !m.translated && m.content && m.lang !== 'Chinese' && isTranslationRetryEligible(m) && !attempted.has(String(m.message_id || '')) && !translatingIdsRef.current.has(String(m.message_id || '')))
        if (!msg) break
        const id = String(msg.message_id || '')
        attempted.add(id)
        processed += 1
        await translateOne(msg, generation, controller.signal)
      }
    })().finally(() => {
      if (translationAbortRef.current === controller) translationAbortRef.current = null
      translationWorkerRunningRef.current = false
      if (!controller.signal.aborted && generation === translationGenerationRef.current) {
        const hasMore = messagesRef.current.some(m => !m.hidden && !m.pending && !m.failed && !String(m.message_id || '').startsWith('tmp-') && !m.translated && m.content && m.lang !== 'Chinese' && isTranslationRetryEligible(m) && !attempted.has(String(m.message_id || '')))
        if (hasMore) setTranslationWorkerTick(prev => prev + 1)
        clearTimeout(translationRetryTimerRef.current)
        const retryDelay = nextTranslationRetryDelay(messagesRef.current)
        if (retryDelay > 0) {
          translationRetryTimerRef.current = setTimeout(() => setTranslationWorkerTick(prev => prev + 1), retryDelay)
        }
      }
    })
  }, [translationQueueVersion, autoTranslate, userId, translationWorkerTick])

  const previewReply = async () => {
    const text = composer.trim()
    const previewMode = mode || 'smart'
    if (!text || !userId || previewMode === 'direct') return
    setPreviewLoading(true)
    setPreviewError(false)
    try {
      const data = await onReply(userId, text, previewMode, { previewOnly: true })
      if (data?.success !== true) throw new Error(data?.detail || t('previewFailed'))
      setPreview(data?.rewrite ? {
        mode: previewMode,
        language: data.rewrite.language,
        message: data.rewrite.message,
        used_fallback: data.rewrite.used_fallback,
        persona: data.rewrite.persona || data.persona || null,
      } : null)
      if (data?.rewrite?.persona !== undefined) setCurrentPersona(data.rewrite.persona)
    } catch {
      setPreviewError(true)
    } finally {
      setPreviewLoading(false)
    }
  }

  const deliverMessage = async (tmpId, target, sourceText, sendMode, optimisticText) => {
    setMessages(prev => prev.map(m => m.message_id === tmpId ? { ...m, pending: true, failed: false, error: '' } : m))
    try {
      const data = await onReply(target, sourceText, sendMode, { idempotencyKey: tmpId })
      if (data?.success !== true) throw new Error(data?.detail || t('sendFailed'))
      const finalText = data?.rewrite?.message || optimisticText
      const platformId = data?.message_id || data?.messageId || null
      const finalId = data?.local_message_id || data?.message_id || tmpId
      const finalLang = normalizeRewriteLanguage(data?.rewrite?.language)
      const queued = Boolean(data?.queued) || data?.status === 'queued'
      setMessages(prev => prev.map(m => m.message_id === tmpId ? {
        ...m,
        message_id: finalId,
        platform_message_id: platformId,
        local_only: !data?.local_message_id,
        content: finalText,
        pending: queued,
        failed: false,
        sent: !queued,
        status: data?.status || (queued ? 'queued' : 'sent'),
        lang: finalLang,
        translated: null,
      } : m))
      if (data?.rewrite?.persona !== undefined) setCurrentPersona(data.rewrite.persona)
      setPreview(data?.rewrite ? { mode: sendMode, language: data.rewrite.language, message: data.rewrite.message, used_fallback: data.rewrite.used_fallback, persona: data.rewrite.persona } : null)
    } catch (error) {
      setMessages(prev => prev.map(m => m.message_id === tmpId ? {
        ...m,
        pending: false,
        failed: true,
        sent: false,
        error: error?.message || t('sendFailed'),
        retryable: error?.retryable !== false,
      } : m))
    }
  }

  const sendMessage = async () => {
    const text = composer.trim()
    if (!text || !userId) return
    const sendMode = mode || 'smart'
    const target = userId
    const tmpId = `tmp-${Date.now()}`
    const optimisticText = sendMode === 'direct' ? text : (preview?.message || text)

    setComposer('')
    setPreview(null)
    setPreviewError(false)
    lastBottomRef.current = true
    setMessages(prev => [...prev, {
      message_id: tmpId,
      session_id: 'pending',
      role: 'assistant',
      content: optimisticText,
      source_text: text,
      target,
      send_mode: sendMode,
      timestamp: Date.now() / 1000,
      hidden: false,
      pending: true,
      failed: false,
      translated: null,
      lang: 'Chinese',
    }])
    await deliverMessage(tmpId, target, text, sendMode, optimisticText)
  }

  const retryMessage = item => {
    if (!item?.failed || item.pending) return
    deliverMessage(item.message_id, item.target || userId, item.source_text || item.content, item.send_mode || 'direct', item.content)
  }

  const insertEmoji = (emoji) => {
    setComposer(prev => `${prev}${emoji}`)
  }

  useLayoutEffect(() => {
    const el = composerRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(140, Math.max(40, el.scrollHeight))}px`
  }, [composer])

  const resizeComposer = event => {
    const el = event.currentTarget
    el.style.height = 'auto'
    el.style.height = `${Math.min(140, Math.max(40, el.scrollHeight))}px`
  }

  const scrollToLatest = () => {
    const el = scrollRef.current
    if (!el) return
    lastBottomRef.current = true
    setNewMessageCount(0)
    el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })
  }

  const onKey = (e) => {
    if (e.isComposing || e.nativeEvent?.isComposing || e.keyCode === 229) return
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      sendMessage()
    }
  }

  const openContactDrawer = () => {
    setContactSaved(false)
    setContactDraft({
      remark: contactProfile?.remark || '',
      notes: contactProfile?.notes || '',
      ai_model: userOverride?.ai_model || '',
      custom_system_prompt: userOverride?.custom_system_prompt || '',
      reply_style: userOverride?.reply_style || '',
    })
    setContactDrawerTab('profile')
    setContactDrawerOpen(true)
  }

  const openPersonaPicker = async () => {
    setHeaderMenuOpen(false)
    setPersonaPickerOpen(true)
    setPersonaLoading(true)
    setPersonaError('')
    try {
      const catalog = await fetchPersonaCatalog()
      const existing = catalog.contact_assignments?.[userId]
      setPersonaCatalog({
        items: catalog.items,
        available: catalog.available,
        plugin_enabled: catalog.plugin_enabled,
      })
      if (existing) {
        const match = catalog.items.find(item => item.id === existing)
        if (match) setCurrentPersona(match)
      } else if (currentPersona && !catalog.items.find(item => item.id === currentPersona.id)) {
        setCurrentPersona(null)
      }
    } catch (error) {
      setPersonaError(error?.message || t('personaLoadFailed'))
    } finally {
      setPersonaLoading(false)
    }
  }

  const assignPersona = async personaId => {
    if (!userId || !personaCatalog.available || personaSaving) return
    setPersonaSaving(true)
    setPersonaError('')
    try {
      await assignPersonaApi(userId, personaId)
      const match = personaCatalog.items.find(item => item.id === personaId)
      setCurrentPersona(personaId === 'default' ? null : match || null)
    } catch (error) {
      setPersonaError(error?.message || t('error'))
    } finally {
      setPersonaSaving(false)
    }
  }

  const saveContactDrawer = async () => {
    if (!userId || !onSaveContactConfig) return
    setContactSaving(true)
    try {
      await onSaveContactConfig(userId, contactDraft)
      setContactSaved(true)
      setTimeout(() => setContactSaved(false), 1600)
    } finally {
      setContactSaving(false)
    }
  }

  const grouped = useMemo(() => {
    const out = []
    let lastDay = ''
    for (const m of messages) {
      // Skip own (assistant/operator) messages when hideOwnMessages is on
      if (hideOwnMessages && (m.role === 'assistant' || m.role === 'operator')) continue
      const k = dayKey(m.timestamp)
      if (k !== lastDay) {
        out.push({ type: 'day', key: k, label: formatDay(m.timestamp, t) })
        lastDay = k
      }
      out.push({ type: 'msg', ...m })
    }
    return out
  }, [messages, hideOwnMessages])

  if (!userId) {
    return <section className={`wx-chat empty is-active${active ? '' : ''}`}><div className="wx-empty wx-chat-empty"><svg viewBox="0 0 64 64"><path d="M11 14h42v30H29l-12 8v-8h-6z"/><path d="M21 25h22M21 33h15"/></svg><strong>{t('selectConversation')}</strong><span>{t('hintWorkspace')}</span></div></section>
  }

  const allowLocalHide = !!uiSettings?.message_ops?.allow_local_hide_delete
  const headerTitle = contactProfile?.remark || userName

  return (
    <section className={`wx-chat is-active${active ? '' : ''}`}>
      <div className="wx-chat-header">
        <button className="wx-icon-btn wx-back-btn" onClick={onBack} aria-label={t('back')} title={t('back')}>
          <svg viewBox="0 0 24 24"><path d="M15 6l-6 6 6 6"/></svg>
        </button>
        <div className="wx-avatar" style={{ background: avatarColor(headerTitle) }}>{initials(headerTitle)}</div>
        <div className="wx-chat-header-meta" onClick={() => { openContactDrawer(); setContactDrawerTab('profile') }} role="button" tabIndex={0}>
          <div className="wx-chat-title">{headerTitle}</div>
          <div className="wx-chat-sub"><span className="wx-online-dot"/><span>{accountLabel || String(platform || 'WA').toUpperCase()} · {accountName}</span></div>
          {currentPersona ? <span className="wx-current-persona">{t('personaCurrent')}: {currentPersona.name}</span> : null}
          </div>
        <div className="wx-chat-header-actions">
          <button className={`wx-icon-btn wx-chat-pin-btn${pinned ? ' active' : ''}`} onClick={onTogglePin} title={pinned ? t('unpin') : t('pin')} aria-label={pinned ? t('unpin') : t('pin')}>
            <svg viewBox="0 0 24 24"><path d="M12 17v5M8 3h8l-2 5 4 2-3 4H9l-3-4 4-2-2-5z"/></svg>
          </button>
          <button className="wx-icon-btn wx-chat-more-btn" onClick={() => setHeaderMenuOpen(prev => !prev)} title={t('more')} aria-label={t('more')}>
            <svg viewBox="0 0 24 24"><circle cx="5" cy="12" r="1.5" fill="currentColor" stroke="none"/><circle cx="12" cy="12" r="1.5" fill="currentColor" stroke="none"/><circle cx="19" cy="12" r="1.5" fill="currentColor" stroke="none"/></svg>
          </button>
          {headerMenuOpen ? <div className="wx-chat-overflow-menu">
            <button type="button" onClick={() => { setHeaderMenuOpen(false); fetchPage(userId, 1, false).catch(() => {}) }}>{t('refresh') || '刷新'}</button>
            <button type="button" onClick={() => { setHeaderMenuOpen(false); openContactDrawer() }}>{t('contactDetails') || '聊天详情'}</button>
            <button type="button" onClick={openPersonaPicker}>{t('personaPicker')}</button>
            <div className="wx-menu-divider"/>
            <button type="button" onClick={() => { setHeaderMenuOpen(false); onOpenSettings() }}>{t('settings') || '全局设置'}</button>
            <button type="button" className={hideOwnMessages ? 'toggle-on' : ''} onClick={() => setHideOwnMessages(prev => !prev)}>
              <span className="wx-menu-label">{t('hideOwnMessages') || '隐藏我方消息'}</span>
              <span className={`wx-toggle ${hideOwnMessages ? 'on' : 'off'}`}>{hideOwnMessages ? t('on') : t('off')}</span>
            </button>
          </div> : null}
        </div>
      </div>

      {!autoTranslate && autoTranslateState?.blockedReason === 'ai_not_configured' ? (
        <button type="button" className="wx-translation-alert" onClick={onOpenSettings}>
          <span>{t('translationAiNotConfigured')}</span><strong>{t('configureNow')}</strong>
        </button>
      ) : null}
      {translationError ? <button type="button" className="wx-translation-alert error" onClick={onOpenSettings}>{translationError}</button> : null}

      {personaPickerOpen ? (
        <div className="wx-drawer-backdrop" onClick={() => setPersonaPickerOpen(false)}>
          <aside className="wx-persona-picker" onClick={e => e.stopPropagation()} role="dialog" aria-modal="true" aria-label={t('personaPicker')}>
            <div className="wx-persona-picker-header"><strong>{t('personaPicker')}</strong><button type="button" className="wx-icon-btn" onClick={() => setPersonaPickerOpen(false)} aria-label={t('dismiss')}><svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18"/></svg></button></div>
            <div className="wx-persona-picker-body">
              <div className="wx-persona-default"><strong>{t('personaDefault')}</strong><span>{defaultReplyStyle}</span><button type="button" className="ghost-btn" disabled={!personaCatalog.available || personaSaving} onClick={() => assignPersona('default')}>{t('personaUse')}</button></div>
              {personaLoading ? <div className="wx-empty-pill">{t('personaLoading')}</div> : null}
              {personaError ? <div className="wx-empty-pill" style={{ color: 'var(--wx-danger)' }}>{personaError}</div> : null}
              {!personaLoading && !personaError && !personaCatalog.available ? <div className="wx-empty-pill">{t('personaUnavailable')}</div> : null}
              <div className="wx-persona-grid">
                {personaCatalog.items.map(persona => <button type="button" key={persona.id} className={`wx-persona-card ${currentPersona?.id === persona.id ? 'active' : ''}`} disabled={!personaCatalog.available || personaSaving} onClick={() => assignPersona(persona.id)}><strong>{persona.name}</strong><span>{persona.description}</span><em>{persona.accent}</em></button>)}
              </div>
            </div>
          </aside>
        </div>
      ) : null}

      <div className="wx-messages" ref={scrollRef} onScroll={onScroll}>
        <div className="wx-messages-inner">
          {hasMore ? <div className="wx-loadmore"><button onClick={loadMore} disabled={loadingMore}>{loadingMore ? t('loading') : t('loadMore')}</button></div> : null}
          {initialLoading ? (
            <div className="wx-skeleton-msg-list" style={{ padding: '16px 14px' }}>
              {[80, 60, 90, 55, 75, 65, 85, 50].map((w, i) => (
                <div key={i} className="wx-skeleton-msg" style={{ justifyContent: i % 2 === 0 ? 'flex-start' : 'flex-end' }}>
                  {i % 2 !== 0 && <div className="wx-skeleton wx-skeleton-avatar" />}
                  <div className={`wx-skeleton wx-skeleton-bubble ${w < 65 ? 'short' : w > 80 ? 'long' : ''} ${i % 2 !== 0 ? '' : 'right'}`} style={{ width: `${w}%` }} />
                  {i % 2 === 0 && <div className="wx-skeleton wx-skeleton-avatar" />}
                </div>
              ))}
            </div>
          ) : null}
          {allowLocalHide && hiddenCount ? <div className="wx-hidden-note">{hiddenCount} {t('hiddenMessages')}</div> : null}
          {!initialLoading && messages.length === 0 ? <div className="wx-empty">{t('noMessages')}</div> : null}
          {grouped.map((item, idx) => {
            if (item.type === 'day') {
              return <div className="wx-day-separator" key={`day-${item.key}-${idx}`}><span>{item.label}</span></div>
            }
            const isOut = item.role === 'assistant'
            const pending = item.pending
            const failed = item.failed
            const statusLabel = failed ? t('sendFailed') : pending ? t('sending') : item.sent ? t('sent') : ''
            const hideTranslation = hiddenTranslations[item.message_id]
            const effectiveHidden = allowLocalHide && item.hidden
            const nextItem = nextMessageInGrouped(grouped, idx)
            const showTime = shouldShowBubbleTime(item, nextItem)
            const translatedText = String(item.translated || '').trim()
            const contentText = String(item.content || '').trim()
            const showTranslation = autoTranslate && !effectiveHidden && !hideTranslation && item.lang && item.lang !== 'Chinese' && translatedText && translatedText !== contentText
            return (
              <div className={`wx-bubble-row ${isOut ? 'out' : 'in'} ${activeMessageId === item.message_id ? 'is-active' : ''}`} key={`${item.message_id}-${idx}`} onClick={() => setActiveMessageId(item.message_id)}>
                <div className="wx-avatar bubble-avatar" style={{ background: avatarColor(isOut ? 'operatorAvatar' : userName) }}>{initials(isOut ? t('operator') : userName)}</div>
                <div>
                  <div className={`wx-bubble ${isOut ? 'out' : 'in'} ${effectiveHidden ? 'hidden' : ''}`}>
                    <div className="wx-bubble-content">
                      {effectiveHidden ? t('hiddenPlaceholder') : <><MessageMedia message={item} />{item.content}</>}
                    </div>
                    {showTranslation ? (
                      <div className="wx-bubble-translation">
                        <span>{translatedText}</span>
                        <button className="wx-bubble-action wx-translation-hide" onClick={(e) => { e.stopPropagation(); setHiddenTranslations(prev => ({ ...prev, [item.message_id]: true })) }}>{t('hideTranslation')}</button>
                      </div>
                    ) : null}
                  </div>
                  {(showTime || statusLabel) ? <div className="wx-bubble-meta">{showTime ? <span>{fmtClock(item.timestamp)}</span> : null}{statusLabel ? <span className={`wx-bubble-status ${failed ? 'failed' : ''}`}>{showTime ? '· ' : ''}{statusLabel}</span> : null}{failed && item.retryable !== false ? <button type="button" className="wx-retry-btn" onClick={e => { e.stopPropagation(); retryMessage(item) }}>{t('retry') || '重试'}</button> : null}</div> : null}
                </div>
                {allowLocalHide && !effectiveHidden ? <div className="wx-bubble-actions"><button className="wx-bubble-action" onClick={(e) => { e.stopPropagation(); onHideMessage(item.message_id) }}>{t('hide')}</button></div> : null}
              </div>
            )
          })}
        </div>
        {newMessageCount > 0 ? <button type="button" className="wx-new-message-btn" onClick={scrollToLatest}>{newMessageCount} {t('newMessages') || '条新消息'} ↓</button> : null}
      </div>

      {contactDrawerOpen ? (
        <div className="wx-drawer-backdrop" onClick={() => setContactDrawerOpen(false)}>
          <aside className="wx-contact-drawer" onClick={e => e.stopPropagation()} role="dialog" aria-modal="true">
            <div className="wx-contact-drawer-hero">
              <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                <div className="wx-avatar lg" style={{ background: avatarColor(contactDraft.remark || userName) }}>{initials(contactDraft.remark || userName)}</div>
                <div style={{ minWidth: 0, flex: 1 }}>
                  <div className="wx-contact-remark">{t('contactDetails') || '聊天详情'}</div>
                  <h3>{contactDraft.remark || userName}</h3>
                  <p>{userName} · {userId}</p>
                </div>
                <button className="wx-icon-btn" onClick={() => setContactDrawerOpen(false)} aria-label={t('dismiss')}>
                  <svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18"/></svg>
                </button>
              </div>
              <div className="wx-contact-drawer-hero-actions">
                <button className="wx-mini-action" onClick={() => { navigator.clipboard?.writeText(userId) }}><svg viewBox="0 0 24 24"><rect x="8" y="3" width="8" height="4" rx="1"/><path d="M8 5H6a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2h-2"/></svg>{t('copyId') || '复制 ID'}</button>
                <button className="wx-mini-action" onClick={() => setContactDrawerTab('ai')}><svg viewBox="0 0 24 24"><path d="M12 2v3M12 19v3M4.2 4.2l2.1 2.1M17.7 17.7l2.1 2.1M2 12h3M19 12h3M4.2 19.8l2.1-2.1M17.7 6.3l2.1-2.1"/><circle cx="12" cy="12" r="4"/></svg>{t('perContactReplyConfig') || 'AI 风格'}</button>
              </div>
            </div>
            <div className="wx-contact-drawer-tabs">
              <button type="button" className={`wx-drawer-tab ${contactDrawerTab === 'profile' ? 'active' : ''}`} onClick={() => setContactDrawerTab('profile')}>{t('contactProfile') || '资料'}</button>
              <button type="button" className={`wx-drawer-tab ${contactDrawerTab === 'history' ? 'active' : ''}`} onClick={() => setContactDrawerTab('history')}>{t('chatHistory') || '聊天记录'}</button>
              <button type="button" className={`wx-drawer-tab ${contactDrawerTab === 'ai' ? 'active' : ''}`} onClick={() => setContactDrawerTab('ai')}>{t('ai') || 'AI'}</button>
            </div>
            <div className="wx-contact-drawer-body">
              {contactDrawerTab === 'profile' ? (
                <div className="wx-contact-card">
                  <div className="wx-contact-card-row">
                    <span className="wx-contact-card-label">{t('contactRemark') || '备注'}</span>
                    <input value={contactDraft.remark || ''} onChange={e => setContactDraft(prev => ({ ...prev, remark: e.target.value }))} placeholder={userName} />
                  </div>
                  <div className="wx-contact-card-row">
                    <span className="wx-contact-card-label">{t('contactNotes') || '联系人说明'}</span>
                    <textarea rows={4} value={contactDraft.notes || ''} onChange={e => setContactDraft(prev => ({ ...prev, notes: e.target.value }))} placeholder="记录这个聊天对象的背景、关系、沟通习惯。" />
                  </div>
                  <div className="wx-contact-card-row">
                    <span className="wx-contact-card-label">{t('basicInfo') || '基本信息'}</span>
                    <div className="wx-contact-meta-list">
                      <div className="wx-contact-meta-row"><span>{t('contactId') || '联系人ID'}</span><strong>{userId}</strong></div>
                      <div className="wx-contact-meta-row"><span>{t('displayName') || '显示名'}</span><strong>{userName}</strong></div>
                    </div>
                  </div>
                </div>
              ) : null}

              {contactDrawerTab === 'history' ? (
                <>
                  <div className="wx-contact-summary-grid">
                    <div className="wx-contact-summary-card"><span>{t('totalMessages') || '消息数'}</span><strong>{total}</strong></div>
                    <div className="wx-contact-summary-card"><span>{t('hiddenMessages') || '隐藏'}</span><strong>{hiddenCount}</strong></div>
                  </div>
                  <div className="wx-history-tips">
                    <span className="wx-contact-card-label">{t('chatHistory') || '聊天记录'}</span>
                    <p>{t('chatHistoryHelp') || '当前窗口就是该联系人的完整聊天记录，可在主聊天区滚动查看；这里保留摘要与快捷入口。'} </p>
                    <button type="button" className="ghost-btn" onClick={() => setContactDrawerOpen(false)}>{t('returnToChat') || '返回聊天继续查看'}</button>
                  </div>
                </>
              ) : null}

              {contactDrawerTab === 'ai' ? (
                <div className="wx-contact-card">
                  <div className="wx-contact-card-row">
                    <span className="wx-contact-card-label">{t('settingAiModel') || 'AI 模型'}</span>
                    <input value={contactDraft.ai_model || ''} onChange={e => setContactDraft(prev => ({ ...prev, ai_model: e.target.value }))} placeholder={defaultAiModel || 'gpt-5.3-codex-spark'} />
                    <span className="wx-contact-card-hint">{t('inheritGlobalModel') || '留空则继承全局模型'}</span>
                  </div>
                  <div className="wx-contact-card-row">
                    <span className="wx-contact-card-label">{t('settingDefaultReplyStyle') || '回复风格'}</span>
                    <textarea rows={3} value={contactDraft.reply_style || ''} onChange={e => setContactDraft(prev => ({ ...prev, reply_style: e.target.value }))} placeholder={defaultReplyStyle || '像熟人聊天，短句，少模板感'} />
                  </div>
                  <div className="wx-contact-card-row">
                    <span className="wx-contact-card-label">{t('settingCustomSystemPrompt') || '系统提示词'}</span>
                    <textarea rows={5} value={contactDraft.custom_system_prompt || ''} onChange={e => setContactDraft(prev => ({ ...prev, custom_system_prompt: e.target.value }))} placeholder="为这个联系人补充专属提示词，例如：更温柔、更口语化、先共情再建议。" />
                  </div>
                </div>
              ) : null}

              <div className="wx-drawer-actions">
                <button type="button" className="ghost-btn" onClick={onOpenContactConfig}>{t('openInSettings') || '去完整设置页'}</button>
                <button type="button" className="wx-primary-btn" onClick={saveContactDrawer} disabled={contactSaving}>{contactSaving ? t('saving') : contactSaved ? `✓ ${t('saved')}` : t('save')}</button>
              </div>
            </div>
          </aside>
        </div>
      ) : null}

      <div className="wx-composer">
        {preview && preview.message && mode !== 'direct' ? <div className="wx-preview-strip"><span>{t('preview') || '预览'}:</span><span className="preview-text">{preview.message}</span>{preview?.persona ? <span className="wx-current-persona">{t('personaCurrent')}: {preview.persona.name}</span> : null}</div> : null}
        {previewError && mode !== 'direct' ? <div className="wx-preview-strip wx-preview-error">{t('previewFailed') || '预览失败'}</div> : null}
        <div className="wx-composer-input wx-wechat-composer-row">
          <button type="button" className="wx-composer-icon-btn" aria-label={t('quickEmoji')} onClick={() => setToolsOpen(prev => !prev)}>
            <svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M8.5 10h.01M15.5 10h.01M8 14c1.1 1.3 2.4 2 4 2s2.9-.7 4-2"/></svg>
          </button>
          <textarea ref={composerRef} value={composer} onChange={e => setComposer(e.target.value)} onInput={resizeComposer} onKeyDown={onKey} placeholder={t('messagePlaceholder')} rows={1} />
          {composer.trim() ? (
            <button type="button" className={`wx-send-btn${sending ? ' sending' : ''}`} onClick={sendMessage} disabled={sending}>
              {sending ? <span className="wx-spinner sm" /> : t('send')}
            </button>
          ) : (
            <button type="button" className={`wx-composer-icon-btn wx-composer-plus${toolsOpen ? ' active' : ''}`} aria-label={t('more') || '更多'} onClick={() => setToolsOpen(prev => !prev)}>
              <svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 8v8M8 12h8"/></svg>
            </button>
          )}
        </div>
        {toolsOpen ? (
          <div className="wx-composer-tools-panel">
            <div className="wx-mode-choices" role="radiogroup" aria-label={t('mode')}>
              <button type="button" role="radio" aria-checked={mode === 'direct'} className={`wx-mode-choice ${mode === 'direct' ? 'active' : ''}`} onClick={() => setMode('direct')}>{t('modeDirect')}</button>
              <button type="button" role="radio" aria-checked={mode === 'smart'} className={`wx-mode-choice ${mode === 'smart' ? 'active' : ''}`} onClick={() => setMode('smart')}>{t('modeSmart')}</button>
              <button type="button" role="radio" aria-checked={mode === 'translate'} className={`wx-mode-choice ${mode === 'translate' ? 'active' : ''}`} onClick={() => setMode('translate')}>{t('modeTranslate')}</button>
              {mode !== 'direct' ? <button type="button" className="wx-mode-choice" onClick={previewReply} disabled={!composer.trim() || previewLoading}>{previewLoading ? t('loading') : (t('preview') || '预览')}</button> : null}
            </div>
            <div className="wx-composer-emoji-grid" aria-label={t('quickEmoji')}>
              {QUICK_EMOJIS.map(emoji => <button key={emoji} type="button" onClick={() => insertEmoji(emoji)}>{emoji}</button>)}
            </div>
          </div>
        ) : null}
      </div>
    </section>
  )
}
