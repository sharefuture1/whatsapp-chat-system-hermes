import { useEffect, useState } from 'react'
import { api } from '../api'
import { fmtTime } from '../format'
import MemorySummary from './MemorySummary'
import ReplyPreview from './ReplyPreview'

export default function ConversationDetail({ detail, onReply, onHideMessage, onHideLatest, sending, sendingMeta, uiSettings }) {
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
    return <section className="panel workspace-panel empty-state luxury-panel"><h2>Select a conversation</h2><div className="subtle">The workspace shows messages, memory, and advanced reply tooling.</div></section>
  }

  const effectivePreview = mode === 'direct'
    ? { mode: 'direct', language: 'direct', message, used_fallback: false }
    : preview

  return (
    <section className="panel workspace-panel elevated luxury-panel">
      <div className="workspace-header">
        <div>
          <div className="eyebrow">Active conversation</div>
          <h2>{detail.user_name}</h2>
          <div className="subtle">{detail.user_id}</div>
        </div>
        <div className="workspace-tags">
          <span className="pill muted">{detail.profile_summary?.language_hint || 'Unknown'}</span>
          <span className={`pill ${detail.profile_summary?.priority === 'high' ? 'danger' : 'ok'}`}>{detail.profile_summary?.priority || 'normal'}</span>
        </div>
      </div>
      <div className="workspace-grid premium-grid">
        <div className="message-column">
          <div className="message-list">
            {detail.messages.map((msg, idx) => (
              <div key={`${msg.session_id}-${idx}`} className={`message ${msg.role} ${msg.hidden ? 'hidden-message' : ''}`}>
                <div className="message-topline">
                  <div className="message-role">{msg.role}</div>
                  <div className="message-time">{fmtTime(msg.timestamp)}</div>
                </div>
                <div className="message-content">{msg.hidden ? '[Hidden in admin console]' : msg.content}</div>
                {!msg.hidden ? <div className="message-actions"><button className="danger-btn small-btn" onClick={() => onHideMessage(msg.message_id || msg.timestamp)}>Hide</button></div> : null}
              </div>
            ))}
          </div>
          <div className="panel luxury-panel bulk-delete-panel">
            <h3>Quick Hide</h3>
            <div className="subtle">Current stack does not support true WhatsApp bilateral revoke. This hides messages in the admin console only.</div>
            <div className="bulk-delete-row">
              <input type="number" min="1" value={bulkCount} onChange={e => setBulkCount(Number(e.target.value) || 1)} />
              <button className="danger-btn" onClick={() => onHideLatest(detail.user_id, bulkCount)}>Hide latest N</button>
            </div>
          </div>
        </div>
        <div className="composer-column">
          <div className="reply-box professional premium-box">
            <div className="reply-toolbar">
              <div>
                <h3>Reply composer</h3>
                <div className="subtle">Direct send, smart rewrite, or translate-first workflow.</div>
              </div>
              <select value={mode} onChange={e => setMode(e.target.value)}>
                <option value="direct">Direct</option>
                <option value="smart">Smart Rewrite</option>
                <option value="translate">Translate-first</option>
              </select>
            </div>
            <textarea value={message} onChange={e => setMessage(e.target.value)} placeholder="Write a response, preview it, then send..." />
            <ReplyPreview preview={effectivePreview && effectivePreview.message ? effectivePreview : null} loading={previewLoading} />
            <div className="reply-actions split">
              <div className="subtle">{sendingMeta ? `Last send: ${sendingMeta.mode}, language: ${sendingMeta.language}` : 'Preview before send to avoid duplicates'}</div>
              <button disabled={sending || !message.trim()} onClick={() => onReply(detail.user_id, message, mode, () => setMessage(''))}>{sending ? 'Sending...' : 'Send Reply'}</button>
            </div>
          </div>
          <MemorySummary detail={detail} />
        </div>
      </div>
    </section>
  )
}
