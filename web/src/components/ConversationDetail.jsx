import { useEffect, useState } from 'react'
import { api } from '../api'
import { useSettings } from '../settings'
import { fmtTime } from '../format'
import MemorySummary from './MemorySummary'
import ReplyPreview from './ReplyPreview'

export default function ConversationDetail({ detail, onReply, onHideMessage, onHideLatest, sending, sendingMeta, uiSettings, onBack, active }) {
  const { t } = useSettings()
  const [message, setMessage] = useState('')
  const [mode, setMode] = useState('direct')
  const [preview, setPreview] = useState(null)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [bulkCount, setBulkCount] = useState(3)

  const userId = detail?.user_id || ''

  useEffect(() => {
    setMessage('')
    setPreview(null)
    setMode(uiSettings?.reply?.default_mode || 'direct')
  }, [userId, uiSettings])

  useEffect(() => {
    if (!userId || !message.trim()) {
      setPreview(null)
      setPreviewLoading(false)
      return
    }
    if (mode === 'direct' || !uiSettings?.ui?.show_preview_before_send) {
      setPreview({ mode: 'direct', language: 'direct', message, used_fallback: false })
      setPreviewLoading(false)
      return
    }
    const controller = new AbortController()
    const timer = setTimeout(async () => {
      setPreviewLoading(true)
      try {
        const data = await api.post('/reply', { target: userId, message, mode, preview_only: true }, { signal: controller.signal })
        if (data?.rewrite) {
          setPreview({
            mode,
            language: data.rewrite.language,
            message: data.rewrite.message,
            used_fallback: data.rewrite.used_fallback,
          })
        }
      } catch {
        // aborted or failed preview: keep the last preview, sending still re-validates server-side
      } finally {
        setPreviewLoading(false)
      }
    }, uiSettings?.reply?.preview_debounce_ms || 320)
    return () => {
      controller.abort()
      clearTimeout(timer)
      setPreviewLoading(false)
    }
  }, [userId, message, mode, uiSettings])

  if (!detail) {
    return (
      <section className={`panel workspace-panel empty-state${active ? ' is-active' : ''}`}>
        <h2>{t('selectConversation')}</h2>
        <div className="subtle">{t('hintWorkspace')}</div>
      </section>
    )
  }

  const effectivePreview = mode === 'direct'
    ? { mode: 'direct', language: 'direct', message, used_fallback: false }
    : preview

  return (
    <section className={`panel workspace-panel elevated${active ? ' is-active' : ''}`}>
      <div className="workspace-header">
        <div className="workspace-title">
          {onBack ? <button className="icon-btn mobile-only" aria-label={t('back')} onClick={onBack}><span aria-hidden="true">‹</span></button> : null}
          <div>
            <div className="eyebrow">{t('activeConversation')}</div>
            <h2>{detail.user_name}</h2>
            <div className="subtle">{detail.user_id}</div>
          </div>
        </div>
        <div className="workspace-tags">
          <span className="pill muted">{detail.profile_summary?.language_hint || 'Unknown'}</span>
          <span className={`pill ${detail.profile_summary?.priority === 'high' ? 'danger' : 'ok'}`}>{detail.profile_summary?.priority || 'normal'}</span>
        </div>
      </div>
      <div className="workspace-grid">
        <div className="message-column">
          <div className="message-list">
            {detail.messages.length === 0 ? (
              <div className="empty-state subtle">{t('noMessages')}</div>
            ) : null}
            {detail.messages.map((msg, idx) => (
              <div key={`${msg.session_id}-${idx}`} className={`message ${msg.role}${msg.hidden ? ' hidden-message' : ''}`}>
                <div className="message-topline">
                  <div className="message-role">{msg.role}</div>
                  <div className="message-time">{fmtTime(msg.timestamp)}</div>
                </div>
                <div className="message-content">{msg.hidden ? t('hiddenPlaceholder') : msg.content}</div>
                {!msg.hidden ? <div className="message-actions"><button className="danger-btn small-btn" onClick={() => onHideMessage(msg.message_id || msg.timestamp)}>{t('hide')}</button></div> : null}
              </div>
            ))}
          </div>
          <div className="panel bulk-delete-panel">
            <h3>{t('quickHide')}</h3>
            <div className="subtle">{t('hintNoRevoke')}</div>
            <div className="bulk-delete-row">
              <input type="number" min="1" value={bulkCount} onChange={e => setBulkCount(Number(e.target.value) || 1)} />
              <button className="danger-btn" onClick={() => onHideLatest(detail.user_id, bulkCount)}>{t('hideLatest')}</button>
            </div>
          </div>
        </div>
        <div className="composer-column">
          <div className="reply-box">
            <div className="reply-toolbar">
              <div>
                <h3>{t('composer')}</h3>
                <div className="subtle">{t('hintComposer')}</div>
              </div>
              <select value={mode} onChange={e => setMode(e.target.value)}>
                <option value="direct">{t('modeDirect')}</option>
                <option value="smart">{t('modeSmart')}</option>
                <option value="translate">{t('modeTranslate')}</option>
              </select>
            </div>
            <textarea value={message} onChange={e => setMessage(e.target.value)} placeholder={t('messagePlaceholder')} />
            <ReplyPreview preview={effectivePreview && effectivePreview.message ? effectivePreview : null} loading={previewLoading} />
            <div className="reply-actions">
              <div className="subtle">{sendingMeta ? `${t('lastSend')}: ${sendingMeta.mode}, ${t('language')}: ${sendingMeta.language}` : t('hintPreview')}</div>
              <button disabled={sending || !message.trim()} onClick={() => onReply(detail.user_id, message, mode, () => setMessage(''))}>{sending ? t('sending') : t('send')}</button>
            </div>
          </div>
          <MemorySummary detail={detail} />
        </div>
      </div>
    </section>
  )
}
