import { useEffect, useState } from 'react'
import { useSettings } from '../settings'
import { api } from '../api'

export default function SchedulerCenterPage({ onBack }) {
  const { t } = useSettings()
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [draft, setDraft] = useState({ target: '', message: '', run_at: '' })
  const [submitting, setSubmitting] = useState(false)
  const [toast, setToast] = useState(null)

  const refresh = async () => {
    setError(null)
    try {
      const data = await api.get('/schedule')
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

  const create = async () => {
    if (!draft.target.trim() || !draft.message.trim() || !draft.run_at) {
      flash(t('scheduleHint'))
      return
    }
    const ts = new Date(draft.run_at).getTime()
    if (Number.isNaN(ts) || ts <= Date.now()) {
      flash(t('schedulePast'))
      return
    }
    setSubmitting(true)
    try {
      await api.post('/schedule', {
        target: draft.target.trim(),
        message: draft.message.trim(),
        run_at: Math.floor(ts / 1000),
        mode: 'direct',
        use_memory: true,
      })
      setDraft({ target: '', message: '', run_at: '' })
      flash(t('scheduleAdded'))
      await refresh()
    } catch (e) {
      flash(e.message || t('error'))
    } finally {
      setSubmitting(false)
    }
  }

  const remove = async id => {
    try {
      await api.delete(`/schedule/${id}`)
      await refresh()
    } catch (e) {
      flash(e.message || t('error'))
    }
  }

  return (
    <section className="wx-page wx-scheduler-center">
      <header className="wx-account-page-header">
        <button className="wx-icon-btn" type="button" onClick={onBack} aria-label={t('back')}>
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m15 5-7 7 7 7" /></svg>
        </button>
        <h2>{t('schedulerTitle')}</h2>
        <button type="button" className="wx-icon-btn" aria-label={t('refresh')} onClick={refresh}>
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 12a8 8 0 1 1-2.34-5.66" /><path d="M20 4v5h-5" /></svg>
        </button>
      </header>

      <div className="wx-cell-group">
        <div className="wx-cell-group-title">{t('pluginToolInfo')}</div>
        <p className="subtle">{t('pluginToolInfoBody')}</p>
      </div>

      <div className="wx-cell-group">
        <div className="wx-cell-group-title">{t('scheduleAdd')}</div>
        <div className="wx-section-list wx-card-list">
          <div className="wx-setting-row multi" style={{ alignItems: 'flex-end' }}>
            <div style={{ display: 'grid', gap: 10, width: '100%' }}>
              <label><span>{t('scheduleTarget')}</span>
                <input value={draft.target} onChange={e => setDraft(prev => ({ ...prev, target: e.target.value }))} placeholder="123456@lid" />
              </label>
              <label><span>{t('scheduleAt')}</span>
                <input type="datetime-local" value={draft.run_at} onChange={e => setDraft(prev => ({ ...prev, run_at: e.target.value }))} />
              </label>
              <label><span>{t('scheduleMessage')}</span>
                <textarea rows={3} value={draft.message} onChange={e => setDraft(prev => ({ ...prev, message: e.target.value }))} />
              </label>
              <div>
                <button type="button" className="wx-primary-btn" onClick={create} disabled={submitting}>
                  {submitting ? t('sending') : t('scheduleCreate')}
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div className="wx-cell-group">
        <div className="wx-cell-group-title">{t('schedulerTitle')} · {items.length}</div>
        {loading ? <div className="wx-empty-pill">{t('loading')}…</div> : null}
        {error ? <div className="wx-empty-pill wx-discover-error">{error}</div> : null}
        {!loading && !error && items.length === 0 ? (
          <div className="wx-empty-pill">{t('schedulerEmpty')}</div>
        ) : null}
        <div className="wx-card-list">
          {items.map(item => (
            <div className="wx-setting-row multi" key={item.id}>
              <div style={{ display: 'grid', gap: 4, width: '100%' }}>
                <strong>{item.target}</strong>
                <span className="subtle">{new Date((item.run_at || 0) * 1000).toLocaleString()}</span>
                <span style={{ fontSize: 13, whiteSpace: 'pre-wrap' }}>{item.message}</span>
              </div>
              <button type="button" className="ghost-btn danger" onClick={() => remove(item.id)}>
                {t('scheduleCancel')}
              </button>
            </div>
          ))}
        </div>
        {!loading && items.length === 0 ? <p className="subtle">{t('scheduleEmptyHint')}</p> : null}
      </div>

      {toast ? <div className="wx-toast">{toast}</div> : null}
    </section>
  )
}
