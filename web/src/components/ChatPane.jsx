import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api'
import { useSettings } from '../settings'
import { fmtClock } from '../format'
import { createConversationRequestTracker } from '../chatSync'

const QUICK_EMOJIS = ['😊', '😂', '🥺', '❤️', '👍', '🙏', '😌', '😉']

function initials(name) {
  if (!name) return '?'
  const trimmed = name.trim()
  if (!trimmed) return '?'
  const parts = trimmed.split(/\s+/).filter(Boolean)
  if (parts.length === 1) return parts[0].slice(0, 2)
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase()
}

function avatarColor(name) {
  const colors = ['#5b8def', '#07c160', '#fa9d3b', '#f44c4c', '#9b59b6', '#16a085', '#e67e22', '#2ecc71']
  let h = 0
  for (const ch of name || '') h = (h * 31 + ch.charCodeAt(0)) >>> 0
  return colors[h % colors.length]
}

function dayKey(ts) {
  const d = new Date(ts * 1000)
  return d.toISOString().slice(0, 10)
}

function formatDay(ts) {
  const d = new Date(ts * 1000)
  const today = new Date()
  const yest = new Date()
  yest.setDate(today.getDate() - 1)
  const same = (a, b) => a.toISOString().slice(0, 10) === b.toISOString().slice(0, 10)
  if (same(d, today)) return 'Today'
  if (same(d, yest)) return 'Yesterday'
  return d.toLocaleDateString()
}

function mergeFreshMessages(serverItems, currentItems) {
  const serverKeys = new Set(serverItems.map(item => `${item.role}:${item.content}`))
  const unresolvedLocal = currentItems.filter(item => {
    const id = String(item.message_id || '')
    if (!id.startsWith('tmp-')) return false
    if (!item.pending && !item.failed) return false
    return !serverKeys.has(`${item.role}:${item.content}`)
  })
  return [...serverItems, ...unresolvedLocal]
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

function mergeNewMessages(prev, incoming) {
  if (!incoming.length) return prev
  const seen = new Set(prev.map(item => String(item.message_id)))
  const additions = incoming.filter(item => !seen.has(String(item.message_id)))
  if (!additions.length) return prev
  return [...prev, ...additions].sort((a, b) => (a.timestamp || 0) - (b.timestamp || 0) || Number(a.message_id || 0) - Number(b.message_id || 0))
}

export default function ChatPane({
  userId,
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
  uiSettings,
  onOpenSettings,
  onOpenContactConfig,
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
  const scrollRef = useRef(null)
  const lastBottomRef = useRef(true)
  const fetchedFor = useRef(null)
  const requestTracker = useRef(createConversationRequestTracker())
  const deltaCursorRef = useRef(0)
  const composerRef = useRef(null)
  const [newMessageCount, setNewMessageCount] = useState(0)

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
    const res = await api.get(`/conversations/${encodeURIComponent(targetUserId)}?page=${p}&page_size=${pageSize}`)
    if (!requestTracker.current.isCurrent(request, targetUserId)) return null
    const items = (res.messages || []).slice().reverse()
    if (appendOlder) {
      setMessages(prev => [...items, ...prev])
    } else {
      setMessages(prev => mergeFreshMessages(items, prev))
    }
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
    requestTracker.current.activate(targetUserId)
    setMessages([])
    setHasMore(false)
    setTotal(0)
    setHiddenCount(0)
    setPage(1)
    fetchedFor.current = null
    deltaCursorRef.current = 0
    setNewMessageCount(0)
    setMode(uiSettings?.reply?.default_mode || 'smart')
    setComposer('')
    setPreview(null)
    setPreviewError(false)
    setActiveMessageId(null)
    setHiddenTranslations({})
    setInitialLoading(true)
    fetchPage(targetUserId, 1, false)
      .then(res => { if (res) lastBottomRef.current = true })
      .catch(() => {})
      .finally(() => {
        if (requestTracker.current.isActive(targetUserId)) setInitialLoading(false)
      })
    return () => {
      requestTracker.current.invalidate()
    }
  }, [userId, pageSize, uiSettings])

  useEffect(() => {
    if (!userId || !refreshTick || fetchedFor.current !== userId) return
    const targetUserId = userId
    const wasAtBottom = lastBottomRef.current
    const drain = async () => {
      let cursor = deltaCursorRef.current || maxMessageId(messages)
      let added = 0
      for (let pageIndex = 0; pageIndex < 10; pageIndex += 1) {
        const request = requestTracker.current.begin(targetUserId)
        const res = await api.get(`/conversations/${encodeURIComponent(targetUserId)}/messages?after_id=${cursor}&limit=100`)
        if (!requestTracker.current.isCurrent(request, targetUserId)) return
        const items = res.messages || []
        if (items.length) {
          added += items.length
          setMessages(prev => mergeNewMessages(prev, items))
          cursor = Number(res.next_after_id || res.max_message_id || maxMessageId(items) || cursor)
          deltaCursorRef.current = Math.max(deltaCursorRef.current, cursor)
        }
        if (!res.has_more || !items.length) break
      }
      if (added) {
        if (wasAtBottom) lastBottomRef.current = true
        else setNewMessageCount(prev => prev + added)
        setTotal(prev => prev + added)
      }
    }
    drain().catch(() => {})
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshTick, userId])

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

  const translateOne = async (msg) => {
    if (!msg?.message_id || msg.translated || msg.lang === 'Chinese' || msg.lang === 'Unknown') return
    try {
      const res = await api.post(`/messages/${msg.message_id}/translate`, { user_id: userId, content: msg.content })
      setMessages(prev => prev.map(m => m.message_id === msg.message_id ? { ...m, translated: res.translated || null, lang: res.lang || m.lang } : m))
    } catch {}
  }

  useEffect(() => {
    if (!uiSettings?.message_ops?.auto_translate) return
    const pending = messages.filter(m => !m.hidden && !m.translated && m.lang && m.lang !== 'Chinese' && m.lang !== 'Unknown')
    if (pending.length === 0) return
    let cancelled = false
    ;(async () => {
      for (const msg of pending.slice(0, 6)) {
        if (cancelled) break
        await translateOne(msg)
      }
    })()
    return () => { cancelled = true }
  }, [messages, uiSettings?.message_ops?.auto_translate, userId])

  const deliverMessage = async (tmpId, target, sourceText, sendMode, optimisticText) => {
    setMessages(prev => prev.map(m => m.message_id === tmpId ? { ...m, pending: true, failed: false, error: '' } : m))
    try {
      const data = await onReply(target, sourceText, sendMode)
      if (data?.success !== true) throw new Error(data?.detail || t('sendFailed'))
      const finalText = data?.rewrite?.message || optimisticText
      const finalId = data?.message_id || data?.messageId || tmpId
      const finalLang = normalizeRewriteLanguage(data?.rewrite?.language)
      setMessages(prev => prev.map(m => m.message_id === tmpId ? { ...m, message_id: finalId, content: finalText, pending: false, failed: false, sent: true, lang: finalLang, translated: null } : m))
      setPreview(data?.rewrite ? { mode: sendMode, language: data.rewrite.language, message: data.rewrite.message, used_fallback: data.rewrite.used_fallback } : null)
      if (target === userId && requestTracker.current.isActive(target)) {
        setTimeout(() => {
          if (requestTracker.current.isActive(target)) fetchPage(target, 1, false).catch(() => {})
        }, 450)
      }
    } catch (error) {
      setMessages(prev => prev.map(m => m.message_id === tmpId ? { ...m, pending: false, failed: true, sent: false, error: error?.message || t('sendFailed'), retryable: error?.retryable !== false } : m))
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
      const k = dayKey(m.timestamp)
      if (k !== lastDay) {
        out.push({ type: 'day', key: k, label: formatDay(m.timestamp) })
        lastDay = k
      }
      out.push({ type: 'msg', ...m })
    }
    return out
  }, [messages])

  if (!userId) {
    return <section className={`wx-chat empty is-active${active ? '' : ''}`}><div className="wx-empty"><div style={{ fontSize: 48, marginBottom: 8 }}>💬</div><div>{t('selectConversation')}</div><div style={{ marginTop: 4, fontSize: 12 }}>{t('hintWorkspace')}</div></div></section>
  }

  const autoTranslate = !!uiSettings?.message_ops?.auto_translate
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
          <div className="wx-chat-sub"><span className={`wx-online-dot ${health ? '' : 'offline'}`} />{health ? t('online') : t('offline')} · {total} {t('totalMessages') || 'msgs'}{allowLocalHide && hiddenCount ? ` · ${hiddenCount} ${t('hiddenMessages')}` : ''}</div>
        </div>
        <div className="wx-chat-header-right">
          <button className="wx-icon-btn" onClick={() => { openContactDrawer(); setContactDrawerTab('profile') }} title={t('contactProfile') || '联系人资料'} aria-label={t('contactProfile') || '联系人资料'}>
            <svg viewBox="0 0 24 24"><circle cx="12" cy="8" r="4"/><path d="M4 20c0-3.5 4-6 8-6s8 2.5 8 6"/></svg>
          </button>
          <button className="wx-icon-btn" onClick={() => { openContactDrawer(); setContactDrawerTab('history') }} title={t('chatHistory') || '聊天记录'} aria-label={t('chatHistory') || '聊天记录'}>
            <svg viewBox="0 0 24 24"><path d="M4 6h16M4 12h16M4 18h10"/></svg>
          </button>
        </div>
      </div>

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
            const showTranslation = autoTranslate && !effectiveHidden && !hideTranslation && item.lang && item.lang !== 'Chinese' && item.lang !== 'Unknown' && translatedText && translatedText !== contentText
            return (
              <div className={`wx-bubble-row ${isOut ? 'out' : 'in'} ${activeMessageId === item.message_id ? 'is-active' : ''}`} key={`${item.message_id}-${idx}`} onClick={() => setActiveMessageId(item.message_id)}>
                {!isOut ? <div className="wx-avatar bubble-avatar" style={{ background: avatarColor(userName) }}>{initials(userName)}</div> : null}
                <div>
                  <div className={`wx-bubble ${isOut ? 'out' : 'in'} ${effectiveHidden ? 'hidden' : ''}`}>{effectiveHidden ? t('hiddenPlaceholder') : item.content}</div>
                  {showTranslation ? (
                    <div className="wx-translation-line">
                      <span className="wx-translation-label">{t('translation')}:</span>
                      <span className="wx-translation-text">{translatedText}</span>
                      <button className="wx-bubble-action wx-translation-hide" onClick={(e) => { e.stopPropagation(); setHiddenTranslations(prev => ({ ...prev, [item.message_id]: true })) }}>{t('hideTranslation')}</button>
                    </div>
                  ) : null}
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
        <div className="wx-composer-toolbar">
          <button type="button" className={`wx-mode-pill ${mode !== 'direct' ? 'active' : ''}`} onClick={() => setMode(mode === 'direct' ? 'smart' : mode === 'smart' ? 'translate' : 'direct')} title={t('mode')}>
            <svg viewBox="0 0 24 24" style={{ width: 13, height: 13, stroke: 'currentColor', fill: 'none', strokeWidth: 2 }}><path d="M4 12h11M11 8l4 4-4 4M20 6v12"/></svg>
            {mode === 'direct' ? t('modeDirect') : mode === 'smart' ? t('modeSmart') : t('modeTranslate')}
            {mode !== 'direct' && <span className="wx-mode-badge">AI</span>}
          </button>
          <div className="wx-emoji-strip" aria-label={t('quickEmoji')}>
            {QUICK_EMOJIS.map(emoji => <button key={emoji} type="button" className="wx-emoji-btn" onClick={() => insertEmoji(emoji)}>{emoji}</button>)}
          </div>
          <div style={{ flex: 1 }} />
          {sendingMeta ? <span style={{ fontSize: 11, color: 'var(--wx-text-muted)' }}>{t('lastSend') || '上次'}: {sendingMeta.mode}</span> : null}
        </div>
        {preview && preview.message && mode !== 'direct' ? <div className="wx-preview-strip"><span>{t('preview') || '预览'}:</span><span className="preview-text">{preview.message}</span></div> : null}
        {previewError && mode !== 'direct' ? <div className="wx-preview-strip wx-preview-error">{t('previewFailed') || '预览失败'}</div> : null}
        <div className="wx-composer-input">
          <textarea ref={composerRef} value={composer} onChange={e => setComposer(e.target.value)} onKeyDown={onKey} placeholder={t('messagePlaceholder')} rows={1} />
          <button type="button" className={`wx-send-btn${sending ? ' sending' : ''}`} onClick={sendMessage} disabled={!composer.trim() || sending}>
            {sending ? <span className="wx-spinner sm" /> : null}
            {!sending && (composer.trim() ? t('send') : t('send') + ' ↗')}
          </button>
        </div>
      </div>
    </section>
  )
}
