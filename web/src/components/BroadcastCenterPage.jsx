import { useEffect, useState } from 'react'
import { useSettings } from '../settings'
import { api } from '../api'

export default function BroadcastCenterPage({ onBack }) {
  const { t } = useSettings()
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [draft, setDraft] = useState({ targets: '', message: '' })
  const [submitting, setSubmitting] = useState(false)
  const [toast, setToast] = useState(null)

  const refresh = async () => {
    setError(null)
    try {
      const data = await api.get('/v1/broadcast')
      setItems(data.items ?? [])
    } catch (e) {
      setError(e.message || t('error'))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    refresh()
  }, [])

  const flash = msg => {
    setToast(msg)
    window.setTimeout(() => setToast(null), 2400)
  }

  const send = async () => {
    const message = draft.message.trim()
    const targets = draft.targets.split(/[,\s]+/).map(item => item.trim()).filter(Boolean)
    if (!message || !targets.length) {
      flash(t('broadcastTargetHint'))
      return
    }
    setSubmitting(true)
    try {
      await api.post('/v1/broadcast', { targets, message, mode: 'direct', use_memory: true })
      setDraft({ targets: '', message: '' })
      flash(t('broadcastDone'))
      await refresh()
    } catch (e) {
      flash(e.message || t('error'))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <section className="wx-page wx-broadcast-center">
      <header className="wx-account-page-header">
        <button className="wx-icon-btn" type="button" onClick={onBack} aria-label={t('back')}>
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m15 5-7 7 7 7" /></svg>
        </button>
        <h2>{t('broadcastTitle')}</h2>
        <button type="button" className="wx-icon-btn" aria-label={t('refresh')} onClick={refresh}>
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 12a8 8 0 1 1-2.34-5.66" /><path d="M20 4v5h-5" /></svg>
        </button>
      </header>

      <div className="wx-cell-group">
        <div className="wx-cell-group-title">{t('pluginToolInfo')}</div>
        <p className="subtle">{t('pluginToolInfoBody')}</p>
      </div>

      <div className="wx-cell-group">
        <div className="wx-cell-group-title">{t('broadcastSend')}</div>
        <div className="wx-section-list wx-card-list">
          <div className="wx-setting-row multi" style={{ alignItems: 'flex-end' }}>
            <div style={{ display: 'grid', gap: 10, width: '100%' }}>
              <label><span>{t('broadcastTargetLabel')}</span>
                <input value={draft.targets} onChange={e => setDraft(prev => ({ ...prev, targets: e.target.value }))} placeholder="123@lid, 456@lid" />
              </label>
              <label><span>{t('broadcastMessageLabel')}</span>
                <textarea rows={3} value={draft.message} onChange={e => setDraft(prev => ({ ...prev, message: e.target.value }))} />
              </label>
              <div>
                <button type="button" className="wx-primary-btn" onClick={send} disabled={submitting}>
                  {submitting ? t('sending') : t('broadcastSend')}
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div className="wx-cell-group">
        <div className="wx-cell-group-title">{t('broadcastTitle')} · {items.length}</div>
        {loading ? <div className="wx-empty-pill">{t('loading')}…</div> : null}
        {error ? <div className="wx-empty-pill wx-discover-error">{error}</div> : null}
        {!loading && !error && items.length === 0 ? (
          <div className="wx-empty-pill">{t('broadcastEmpty')}</div>
        ) : null}
        <div className="wx-card-list">
          {items.map(item => (
            <div className="wx-setting-row multi" key={item.id}>
              <div style={{ display: 'grid', gap: 4, width: '100%' }}>
                <strong>{(item.targets || []).length} {t('broadcastTargetLabel')}</strong>
                <span className="subtle">{new Date((item.created_at || 0) * 1000).toLocaleString()}</span>
                <span style={{ fontSize: 13, whiteSpace: 'pre-wrap' }}>{item.message}</span>
                <span className="subtle">
                  ✓ {(item.results || []).filter(result => result.success).length}
                  {' / '}
                  ✗ {(item.results || []).filter(result => !result.success).length}
                </span>
              </div>
            </div>
          ))}
        </div>
      </div>

      {toast ? <div className="wx-toast">{toast}</div> : null}
    </section>
  )
}
