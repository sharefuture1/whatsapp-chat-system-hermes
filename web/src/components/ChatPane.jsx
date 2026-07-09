import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api'
import { useSettings } from '../settings'
import { fmtTime } from '../format'

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
  onBack,
  onReply,
  onHideMessage,
  sending,
  sendingMeta,
  uiSettings,
  onOpenSettings,
  onTogglePin,
  pinned,
  active,
  health,
  onNextConversation,
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
  const [hiddenTranslations, setHiddenTranslations] = useState({})
  const scrollRef = useRef(null)
  const lastBottomRef = useRef(true)
  const fetchedFor = useRef(null)

  useEffect(() => {
    if (mode === 'direct' || !uiSettings?.ui?.show_preview_before_send) {
      setPreview({ mode: 'direct', language: 'direct', message: composer, used_fallback: false })
      return
    }
    if (!userId || !composer.trim()) {
      setPreview(null)
      return
    }
    const controller = new AbortController()
    const timer = setTimeout(async () => {
      setPreviewLoading(true)
      try {
        const data = await api.post('/reply', { target: userId, message: composer, mode, preview_only: true }, { signal: controller.signal })
        if (data?.rewrite) {
          setPreview({ mode, language: data.rewrite.language, message: data.rewrite.message, used_fallback: data.rewrite.used_fallback })
        }
      } catch {} finally {
        setPreviewLoading(false)
      }
    }, uiSettings?.reply?.preview_debounce_ms || 320)
    return () => { controller.abort(); clearTimeout(timer) }
  }, [userId, composer, mode, uiSettings])

  const fetchPage = async (p, appendOlder = false) => {
    const res = await api.get(`/conversations/${encodeURIComponent(userId)}?page=${p}&page_size=${pageSize}`)
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
    return res
  }

  useEffect(() => {
    if (!userId) {
      setMessages([])
      setHasMore(false)
      setTotal(0)
      setHiddenCount(0)
      setPage(1)
      fetchedFor.current = null
      return
    }
    if (fetchedFor.current === userId) return
    fetchedFor.current = userId
    setInitialLoading(true)
    setPage(1)
    setMessages([])
    setHasMore(false)
    setTotal(0)
    setHiddenCount(0)
    setMode(uiSettings?.reply?.default_mode || 'smart')
    setComposer('')
    setPreview(null)
    setHiddenTranslations({})
    fetchPage(1, false)
      .then(() => { lastBottomRef.current = true })
      .catch(() => {})
      .finally(() => setInitialLoading(false))
  }, [userId, pageSize, uiSettings])

  useEffect(() => {
    if (!userId || !refreshTick || fetchedFor.current !== userId) return
    const afterId = maxMessageId(messages)
    if (!afterId) {
      fetchPage(1, false).catch(() => {})
      return
    }
    api.get(`/conversations/${encodeURIComponent(userId)}/messages?after_id=${afterId}&limit=100`)
      .then(res => {
        const items = res.messages || []
        if (!items.length) return
        lastBottomRef.current = true
        setMessages(prev => mergeNewMessages(prev, items))
        setTotal(prev => Math.max(prev, prev + items.length))
      })
      .catch(() => {})
  }, [refreshTick, userId, messages])

  const loadMore = async () => {
    if (loadingMore || !hasMore || !userId) return
    setLoadingMore(true)
    try {
      const next = page + 1
      const container = scrollRef.current
      const prevHeight = container ? container.scrollHeight : 0
      await fetchPage(next, true)
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
  }, [messages.length])

  const onScroll = () => {
    const el = scrollRef.current
    if (!el) return
    if (el.scrollTop < 60 && hasMore && !loadingMore) loadMore()
    const distFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight
    lastBottomRef.current = distFromBottom < 80
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

  const sendMessage = async () => {
    const text = composer.trim()
    if (!text || !userId) return
    const sendMode = mode || 'smart'
    const tmpId = `tmp-${Date.now()}`
    const optimisticText = sendMode === 'direct' ? text : (preview?.message || text)

    setComposer('')
    setPreview(null)
    lastBottomRef.current = true
    setMessages(prev => [
      ...prev,
      {
        message_id: tmpId,
        session_id: 'pending',
        role: 'assistant',
        content: optimisticText,
        timestamp: Date.now() / 1000,
        hidden: false,
        pending: true,
        translated: null,
        lang: 'Chinese',
      },
    ])

    try {
      const data = await onReply(userId, text, sendMode)
      const finalText = data?.rewrite?.message || optimisticText
      const finalId = data?.message_id || data?.messageId || tmpId
      const finalLang = normalizeRewriteLanguage(data?.rewrite?.language)
      setMessages(prev => prev.map(m => m.message_id === tmpId ? { ...m, message_id: finalId, content: finalText, pending: false, sent: true, lang: finalLang, translated: null } : m))
      setTimeout(() => fetchPage(1, false).catch(() => {}), 450)
    } catch {
      setMessages(prev => prev.map(m => m.message_id === tmpId ? { ...m, pending: false, failed: true } : m))
    }
  }

  const insertEmoji = (emoji) => {
    setComposer(prev => `${prev}${emoji}`)
  }

  const onKey = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      sendMessage()
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

  const isPinned = pinned?.includes(userId)
  const autoTranslate = !!uiSettings?.message_ops?.auto_translate
  const allowLocalHide = !!uiSettings?.message_ops?.allow_local_hide_delete

  return (
    <section className={`wx-chat is-active${active ? '' : ''}`}>
      <div className="wx-chat-header">
        <button className="wx-icon-btn" onClick={onNextConversation} aria-label={t('nextChat')} title={t('nextChat')}><span aria-hidden="true">↻</span></button>
        <div className="wx-avatar" style={{ background: avatarColor(userName) }}>{initials(userName)}</div>
        <div className="wx-chat-header-meta">
          <div className="wx-chat-title">{userName}</div>
          <div className="wx-chat-sub"><span className={`wx-online-dot ${health ? '' : 'offline'}`} />{health ? t('online') : t('offline')} · {total} {t('totalMessages') || 'msgs'}{hiddenCount ? ` · ${hiddenCount} ${t('hiddenMessages')}` : ''}</div>
        </div>
        <div className="wx-chat-header-right">
          <button className="wx-icon-btn" onClick={() => onTogglePin(userId)} title={isPinned ? t('unpin') : t('pin')}><span aria-hidden="true">{isPinned ? '★' : '☆'}</span></button>
          <button className={`wx-icon-btn ${autoTranslate ? '' : 'off'}`} onClick={onOpenSettings} title={t('autoTranslate')}><span aria-hidden="true">译</span></button>
          <button className="wx-icon-btn" onClick={onOpenSettings} title={t('settings')}><span aria-hidden="true">⚙</span></button>
        </div>
      </div>

      <div className="wx-messages" ref={scrollRef} onScroll={onScroll}>
        <div className="wx-messages-inner">
          {hasMore ? <div className="wx-loadmore"><button onClick={loadMore} disabled={loadingMore}>{loadingMore ? t('loading') : t('loadMore')}</button></div> : null}
          {initialLoading ? <div className="wx-empty">{t('loading')}</div> : null}
          {hiddenCount ? <div className="wx-hidden-note">{hiddenCount} {t('hiddenMessages')}</div> : null}
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
            return (
              <div className={`wx-bubble-row ${isOut ? 'out' : 'in'}`} key={`${item.message_id}-${idx}`}>
                {!isOut ? <div className="wx-avatar bubble-avatar" style={{ background: avatarColor(userName) }}>{initials(userName)}</div> : null}
                <div>
                  <div className={`wx-bubble ${isOut ? 'out' : 'in'} ${item.hidden ? 'hidden' : ''}`}>{item.hidden ? t('hiddenPlaceholder') : item.content}</div>
                  {autoTranslate && !item.hidden && !hideTranslation && item.lang && item.lang !== 'Chinese' && item.lang !== 'Unknown' ? (
                    <div className="wx-translation-line">
                      <span className="wx-translation-label">{t('translation')}:</span>
                      <span className="wx-translation-text">{item.translated || t('translating')}</span>
                      {item.translated ? <button className="wx-bubble-action" onClick={() => setHiddenTranslations(prev => ({ ...prev, [item.message_id]: true }))}>{t('hideTranslation')}</button> : null}
                    </div>
                  ) : null}
                  <div className="wx-bubble-meta"><span>{fmtTime(item.timestamp)}</span>{statusLabel ? <span className={`wx-bubble-status ${failed ? 'failed' : ''}`}>· {statusLabel}</span> : null}</div>
                </div>
                {allowLocalHide && !item.hidden ? <div className="wx-bubble-actions"><button className="wx-bubble-action" onClick={() => onHideMessage(item.message_id)}>{t('hide')}</button></div> : null}
              </div>
            )
          })}
        </div>
      </div>

      <div className="wx-composer">
        <div className="wx-composer-toolbar">
          <button className={`wx-mode-pill ${mode !== 'direct' ? 'active' : ''}`} onClick={() => setMode(mode === 'direct' ? 'smart' : mode === 'smart' ? 'translate' : 'direct')} title={t('mode')}>{mode === 'direct' ? t('modeDirect') : mode === 'smart' ? t('modeSmart') : t('modeTranslate')}</button>
          <div className="wx-emoji-strip" aria-label={t('quickEmoji')}>
            {QUICK_EMOJIS.map(emoji => <button key={emoji} className="wx-emoji-btn" onClick={() => insertEmoji(emoji)}>{emoji}</button>)}
          </div>
          <div style={{ flex: 1 }} />
          <div className="subtle" style={{ fontSize: 12 }}>{sendingMeta ? `${t('lastSend')}: ${sendingMeta.mode}` : ''}</div>
        </div>
        {preview && preview.message && mode !== 'direct' ? <div className="wx-preview-strip">{previewLoading ? t('generatingPreview') : <><span style={{ marginRight: 4 }}>{t('preview')}:</span><span className="preview-text">{preview.message}</span></>}</div> : null}
        <div className="wx-composer-input">
          <textarea value={composer} onChange={e => setComposer(e.target.value)} onKeyDown={onKey} placeholder={t('messagePlaceholder')} rows={1} style={{ height: Math.min(140, Math.max(40, composer.split('\n').length * 22 + 16)) }} />
          <button className="wx-send-btn" onClick={sendMessage} disabled={!composer.trim() || sending}>{sending ? '...' : t('send')}</button>
        </div>
      </div>
    </section>
  )
}
