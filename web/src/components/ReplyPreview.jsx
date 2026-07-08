export default function ReplyPreview({ preview, loading }) {
  if (loading) {
    return <div className="reply-preview-card"><div className="subtle">Generating smart preview…</div></div>
  }
  if (!preview) return null
  return (
    <div className="reply-preview-card">
      <div className="reply-preview-topline">
        <span className="pill muted">{preview.mode}</span>
        <span className={`pill ${preview.used_fallback ? 'danger' : 'ok'}`}>{preview.used_fallback ? 'fallback' : 'model'}</span>
      </div>
      <div className="reply-preview-meta">Language: {preview.language || 'direct'}</div>
      <div className="reply-preview-message">{preview.message}</div>
    </div>
  )
}
