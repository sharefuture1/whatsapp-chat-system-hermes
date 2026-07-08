import { useSettings } from '../settings'

export default function ReplyPreview({ preview, loading }) {
  const { t } = useSettings()
  if (loading) {
    return <div className="reply-preview-card"><div className="subtle">{t('generatingPreview')}</div></div>
  }
  if (!preview) return null
  return (
    <div className="reply-preview-card">
      <div className="reply-preview-topline">
        <span className="pill muted">{preview.mode}</span>
        <span className={`pill ${preview.used_fallback ? 'danger' : 'ok'}`}>{preview.used_fallback ? t('fallback') : t('model')}</span>
      </div>
      <div className="reply-preview-meta">{t('language')}: {preview.language || 'direct'}</div>
      <div className="reply-preview-message">{preview.message}</div>
    </div>
  )
}
