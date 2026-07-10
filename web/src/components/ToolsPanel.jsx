import { useEffect, useMemo, useState } from 'react'
import { useSettings } from '../settings'
import { api } from '../api'

function fmtTime(ts) {
  if (!ts) return ''
  try {
    const d = new Date(Number(ts) * 1000)
    return d.toLocaleString()
  } catch { return String(ts) }
}

export default function ToolsPanel() {
  const { t } = useSettings()
  const [scheduleItems, setScheduleItems] = useState([])
  const [broadcastItems, setBroadcastItems] = useState([])
  const [plugins, setPlugins] = useState([])
  const [pluginFilter, setPluginFilter] = useState('all')
  const [broadcastTargets, setBroadcastTargets] = useState('')
  const [broadcastMessage, setBroadcastMessage] = useState('')
  const [broadcastMode, setBroadcastMode] = useState('smart')
  const [broadcastRunning, setBroadcastRunning] = useState(false)
  const [scheduleTarget, setScheduleTarget] = useState('')
  const [scheduleMessage, setScheduleMessage] = useState('')
  const [scheduleWhen, setScheduleWhen] = useState('')
  const [scheduleMode, setScheduleMode] = useState('smart')
  const [toast, setToast] = useState(null)
  const [error, setError] = useState(null)

  const flash = msg => {
    setToast(msg)
    setTimeout(() => setToast(null), 2400)
  }

  const loadAll = async () => {
    setError(null)
    try {
      const [s, b, p] = await Promise.all([
        api.get('/schedule').catch(() => ({ items: [] })),
        api.get('/broadcast').catch(() => ({ items: [] })),
        api.get('/plugins').catch(() => ({ items: [] })),
      ])
      setScheduleItems(s.items || [])
      setBroadcastItems(b.items || [])
      setPlugins(p.items || [])
    } catch (e) {
      setError(e.message)
    }
  }

  useEffect(() => { loadAll() }, [])

  const addSchedule = async () => {
    if (!scheduleTarget || !scheduleMessage || !scheduleWhen) {
      flash(t('scheduleHint') || 'Target, message and time are required')
      return
    }
    const runAt = Math.floor(new Date(scheduleWhen).getTime() / 1000)
    if (!runAt || runAt < Math.floor(Date.now() / 1000)) {
      flash(t('schedulePast') || 'Pick a future time')
      return
    }
    try {
      const res = await api.post('/schedule', {
        target: scheduleTarget,
        message: scheduleMessage,
        run_at: runAt,
        mode: scheduleMode,
        use_memory: true,
      })
      setScheduleItems(res.items || [])
      setScheduleTarget('')
      setScheduleMessage('')
      setScheduleWhen('')
      flash(t('scheduleAdded') || 'Scheduled')
    } catch (e) {
      flash(e.message)
    }
  }

  const removeSchedule = async id => {
    try {
      const res = await api.delete(`/schedule/${id}`)
      setScheduleItems(res.items || [])
    } catch (e) { flash(e.message) }
  }

  const sendBroadcast = async () => {
    if (!broadcastMessage) return
    const targets = broadcastTargets.split(/[,\s]+/).map(s => s.trim()).filter(Boolean)
    if (!targets.length) {
      flash(t('broadcastTargetHint') || 'Add at least one target')
      return
    }
    setBroadcastRunning(true)
    try {
      const res = await api.post('/broadcast', {
        targets,
        message: broadcastMessage,
        mode: broadcastMode,
        use_memory: true,
      })
      const succeeded = Number(res.succeeded ?? res.entry?.results?.filter(r => r.success).length ?? 0)
      const failed = Number(res.failed ?? Math.max(0, targets.length - succeeded))
      flash(`${t('broadcastDone') || 'Broadcast'}: ${succeeded}/${targets.length}${failed ? ` · ${failed} ${t('sendFailed') || 'failed'}` : ''}`)
      if (failed === 0) setBroadcastMessage('')
      await loadAll()
    } catch (e) {
      flash(e.message)
    } finally {
      setBroadcastRunning(false)
    }
  }

  const togglePlugin = async plugin => {
    try {
      await api.post('/plugins/toggle', { plugin_id: plugin.id, enabled: !plugin.enabled })
      flash(`${plugin.name}: ${!plugin.enabled ? t('enabled') : t('disabled')}`)
      loadAll()
    } catch (e) { flash(e.message) }
  }

  const removePlugin = async plugin => {
    if (!window.confirm(`${t('removePluginConfirm')} (${plugin.name})`)) return
    try {
      await api.delete(`/plugins/${plugin.id}`)
      flash(t('removed') || 'Removed')
      loadAll()
    } catch (e) { flash(e.message) }
  }

  const enabledCount = useMemo(() => plugins.filter(p => p.enabled).length, [plugins])
  const filteredPlugins = useMemo(() => {
    if (pluginFilter === 'all') return plugins
    return plugins.filter(p => p.category === pluginFilter)
  }, [plugins, pluginFilter])

  return (
    <div className="settings-section">
      <div className="wx-cell-group" style={{ paddingLeft: 0, paddingRight: 0 }}>
        <div className="wx-cell-group-title" style={{ paddingLeft: 0 }}>{t('scheduleTitle') || 'Scheduled send'} ({scheduleItems.length})</div>
        <div className="wx-section-list wx-card-list">
          <div className="wx-setting-row multi" style={{ alignItems: 'flex-end' }}>
            <div style={{ display: 'grid', gap: 10, width: '100%' }}>
              <div className="settings-grid">
                <label><span>{t('broadcastTarget') || 'Target ID'}</span><input value={scheduleTarget} onChange={e => setScheduleTarget(e.target.value)} placeholder="123456@lid" /></label>
                <label><span>{t('whenToSend') || 'When'}</span><input type="datetime-local" value={scheduleWhen} onChange={e => setScheduleWhen(e.target.value)} /></label>
                <label><span>{t('mode')}</span><select value={scheduleMode} onChange={e => setScheduleMode(e.target.value)}>
                  <option value="smart">{t('modeSmart')}</option>
                  <option value="translate">{t('modeTranslate')}</option>
                  <option value="direct">{t('modeDirect')}</option>
                </select></label>
              </div>
              <label><span>{t('messagePlaceholder')}</span><textarea rows={3} value={scheduleMessage} onChange={e => setScheduleMessage(e.target.value)} placeholder={t('scheduleMessageHelp') || 'Message to send at the scheduled time'} /></label>
              <div><button type="button" className="wx-primary-btn" onClick={addSchedule}>{t('scheduleAdd') || 'Schedule'}</button></div>
            </div>
          </div>
          {scheduleItems.length === 0 ? <div className="wx-empty-pill">—</div> : null}
          {scheduleItems.map(item => (
            <div className="wx-setting-row multi" key={item.id}>
              <div style={{ display: 'grid', gap: 4, width: '100%' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
                  <strong>{item.target}</strong>
                  <span className="wx-pill-mini brand">{item.mode}</span>
                </div>
                <span style={{ fontSize: 12, color: 'var(--wx-text-muted)' }}>{fmtTime(item.run_at)}</span>
                <span style={{ fontSize: 13, whiteSpace: 'pre-wrap' }}>{item.message}</span>
              </div>
              <button type="button" className="ghost-btn danger" onClick={() => removeSchedule(item.id)}>{t('delete')}</button>
            </div>
          ))}
        </div>
      </div>

      <div className="wx-cell-group" style={{ paddingLeft: 0, paddingRight: 0 }}>
        <div className="wx-cell-group-title" style={{ paddingLeft: 0 }}>{t('broadcastTitle') || 'Mass broadcast'} ({broadcastItems.length})</div>
        <div className="wx-section-list wx-card-list">
          <div className="wx-setting-row multi" style={{ alignItems: 'flex-end' }}>
            <div style={{ display: 'grid', gap: 10, width: '100%' }}>
              <label><span>{t('broadcastTarget') || 'Targets (comma separated)'}</span><input value={broadcastTargets} onChange={e => setBroadcastTargets(e.target.value)} placeholder="123@lid, 456@lid, 789@lid" /></label>
              <label><span>{t('mode')}</span><select value={broadcastMode} onChange={e => setBroadcastMode(e.target.value)}>
                <option value="smart">{t('modeSmart')}</option>
                <option value="translate">{t('modeTranslate')}</option>
                <option value="direct">{t('modeDirect')}</option>
              </select></label>
              <label><span>{t('messagePlaceholder')}</span><textarea rows={3} value={broadcastMessage} onChange={e => setBroadcastMessage(e.target.value)} placeholder={t('broadcastMessageHelp') || 'Same message to send to all selected targets'} /></label>
              <div><button type="button" className="wx-primary-btn" onClick={sendBroadcast} disabled={broadcastRunning}>{broadcastRunning ? '...' : (t('sendBroadcast') || 'Send to all')}</button></div>
            </div>
          </div>
          {broadcastItems.length === 0 ? <div className="wx-empty-pill">—</div> : null}
          {broadcastItems.map(item => (
            <div className="wx-setting-row multi" key={item.id}>
              <div style={{ display: 'grid', gap: 4, width: '100%' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
                  <strong>{(item.targets || []).length} {t('targets') || 'targets'}</strong>
                  <span className="wx-pill-mini brand">{item.mode}</span>
                </div>
                <span style={{ fontSize: 12, color: 'var(--wx-text-muted)' }}>{fmtTime(item.created_at)}</span>
                <span style={{ fontSize: 13, whiteSpace: 'pre-wrap' }}>{item.message}</span>
                <span style={{ fontSize: 11, color: 'var(--wx-text-muted)' }}>
                  ✓ {(item.results || []).filter(r => r.success).length} / ✗ {(item.results || []).filter(r => !r.success).length}
                </span>
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="wx-cell-group" style={{ paddingLeft: 0, paddingRight: 0 }}>
        <div className="wx-cell-group-title" style={{ paddingLeft: 0, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span>{t('pluginCenter') || 'Plugin Center'} ({enabledCount}/{plugins.length})</span>
          <button type="button" className="wx-inline-btn" onClick={loadAll}>{t('refresh') || 'Refresh'}</button>
        </div>
        <div className="wx-plugin-filters">
          {['all', 'messaging', 'productivity', 'memory', 'media', 'analytics'].map(cat => (
            <button
              type="button"
              key={cat}
              className={`wx-filter-chip ${pluginFilter === cat ? 'active' : ''}`}
              onClick={() => setPluginFilter(cat)}
            >
              {cat}
            </button>
          ))}
        </div>
        {error ? <div className="wx-empty-pill" style={{ color: 'var(--wx-danger)' }}>{error}</div> : null}
        {filteredPlugins.length === 0 ? <div className="wx-empty-pill">—</div> : null}
        <div className="wx-plugin-list">
          {filteredPlugins.map(plugin => (
            <div className={`wx-plugin-card ${plugin.enabled ? '' : 'is-off'}`} key={plugin.id}>
              <div className="wx-plugin-body" style={{ width: '100%' }}>
                <div className="wx-plugin-row1">
                  <div className="wx-plugin-name">{plugin.name}</div>
                  <label className="wx-switch">
                    <input type="checkbox" checked={plugin.enabled} onChange={() => togglePlugin(plugin)} />
                    <span className="wx-switch-slider" />
                  </label>
                </div>
                <div className="wx-plugin-desc">{plugin.description}</div>
                <div className="wx-plugin-meta">
                  <span className="wx-pill-mini brand">{plugin.category}</span>
                  {plugin.builtin ? <span className="wx-pill-mini">{t('builtin') || 'Built-in'}</span> : null}
                  <span className={`wx-pill-mini ${plugin.enabled ? 'ok' : 'danger'}`}>{plugin.enabled ? t('enabled') || 'On' : t('disabled') || 'Off'}</span>
                  <button type="button" className="wx-inline-btn" style={{ marginLeft: 'auto' }} onClick={() => removePlugin(plugin)}>{t('remove') || 'Remove'}</button>
                </div>
                <div className="wx-plugin-status subtle">{plugin.enabled ? (plugin.status_when_on || (t('statusOn') || '已开启')) : (t('statusOff') || '已关闭')}</div>
                {plugin.hooks && plugin.hooks.length ? (
                  <ul className="wx-plugin-hooks">
                    {plugin.hooks.map(h => <li key={h}><code>{h}</code></li>)}
                  </ul>
                ) : null}
              </div>
            </div>
          ))}
        </div>
      </div>

      {toast ? <div className="wx-toast">{toast}</div> : null}
    </div>
  )
}