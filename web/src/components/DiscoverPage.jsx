import { useEffect, useState } from 'react'
import { useSettings } from '../settings'
import { api } from '../api'

const CATEGORY_META = {
  messaging: { label: 'Messaging', accent: '#07c160' },
  productivity: { label: 'Productivity', accent: '#5b8def' },
  memory: { label: 'Memory', accent: '#9b59b6' },
  media: { label: 'Media', accent: '#fa9d3b' },
  analytics: { label: 'Analytics', accent: '#16a085' },
}

const ICON_BY_CATEGORY = {
  messaging: (
    <svg viewBox="0 0 24 24"><path d="M4 5h16a1 1 0 0 1 1 1v11a1 1 0 0 1-1 1h-9l-4 3v-3H4a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1z"/></svg>
  ),
  productivity: (
    <svg viewBox="0 0 24 24"><path d="M12 2v4M12 18v4M4 12H2M22 12h-2M5 5l3 3M16 16l3 3M5 19l3-3M16 8l3-3"/><circle cx="12" cy="12" r="4"/></svg>
  ),
  memory: (
    <svg viewBox="0 0 24 24"><path d="M3 5a2 2 0 0 1 2-2h6v18H5a2 2 0 0 1-2-2zM21 5a2 2 0 0 0-2-2h-6v18h6a2 2 0 0 0 2-2zM12 3v18"/></svg>
  ),
  media: (
    <svg viewBox="0 0 24 24"><rect x="3" y="5" width="18" height="14" rx="2"/><path d="M10 9l5 3-5 3z"/></svg>
  ),
  analytics: (
    <svg viewBox="0 0 24 24"><path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/></svg>
  ),
}

export default function DiscoverPage({ dashboard, channels, conversations }) {
  const { t } = useSettings()
  const [plugins, setPlugins] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [toast, setToast] = useState(null)
  const [filter, setFilter] = useState('all')
  const stats = dashboard?.stats || {}

  const showToast = msg => {
    setToast(msg)
    setTimeout(() => setToast(null), 2400)
  }

  const refresh = async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await api.get('/plugins')
      setPlugins(data.items || [])
    } catch (e) {
      setError(e.message || 'Failed')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { refresh() }, [])

  const toggle = async (plugin) => {
    try {
      await api.post('/plugins/toggle', { plugin_id: plugin.id, enabled: !plugin.enabled })
      showToast(`${plugin.name}: ${!plugin.enabled ? t('enabled') : t('disabled')}`)
      refresh()
    } catch (e) {
      showToast(e.message)
    }
  }

  const remove = async (plugin) => {
    if (!window.confirm(`${t('removePluginConfirm')} (${plugin.name})`)) return
    try {
      await api.delete(`/plugins/${plugin.id}`)
      showToast(`${plugin.name}: ${t('removed')}`)
      refresh()
    } catch (e) {
      showToast(e.message)
    }
  }

  const categories = ['all', ...Object.keys(CATEGORY_META)]
  const filtered = filter === 'all' ? plugins : plugins.filter(p => p.category === filter)
  const enabledCount = plugins.filter(p => p.enabled).length

  const overviewCards = [
    { label: t('totalConversations'), value: stats.total_conversations ?? '—', accent: '#5b8def' },
    { label: t('highPriority'), value: stats.high_priority_conversations ?? '—', accent: '#fa5151' },
    { label: t('totalMessages'), value: stats.total_messages ?? '—', accent: '#07c160' },
    { label: t('activeChannels'), value: channels?.length ?? 0, accent: '#fa9d3b' },
    { label: t('pluginsEnabled') || 'Plugins on', value: `${enabledCount}/${plugins.length || '–'}`, accent: '#9b59b6' },
    { label: t('contactsCount') || 'Contacts', value: conversations?.length ?? '—', accent: '#16a085' },
  ]

  return (
    <section className="wx-page wx-discover-page">
      <div className="wx-page-header" style={{ paddingTop: 18 }}>
        <h2 style={{ fontSize: 22, fontWeight: 700, letterSpacing: -.3 }}>{t('tabDiscover') || '发现'}</h2>
        <p style={{ margin: '6px 0 0', fontSize: 12, color: 'var(--wx-text-muted)' }}>{t('discoverSubtitle') || 'Tools, plugins and shortcuts for your workspace'}</p>
      </div>

      <div className="wx-cell-group">
        <div className="wx-cell-group-title">{t('overview') || '总览'}</div>
        <div className="wx-discover-grid">
          {overviewCards.map(card => (
            <div className="wx-discover-card" key={card.label} style={{ borderTop: `3px solid ${card.accent}` }}>
              <div className="wx-info-title">{card.label}</div>
              <div className="wx-info-value">{card.value}</div>
            </div>
          ))}
        </div>
      </div>

      <div className="wx-cell-group">
        <div className="wx-cell-group-title" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span>{t('pluginCenter') || 'Plugin Center'} · {enabledCount}/{plugins.length}</span>
          <button type="button" className="wx-inline-btn" onClick={refresh}>{t('refresh') || 'Refresh'}</button>
        </div>
        <div className="wx-plugin-filters">
          {categories.map(cat => (
            <button
              type="button"
              key={cat}
              className={`wx-filter-chip ${filter === cat ? 'active' : ''}`}
              onClick={() => setFilter(cat)}
            >
              {cat === 'all' ? (t('all') || 'All') : (CATEGORY_META[cat].label)}
            </button>
          ))}
        </div>
        {error ? <div className="wx-empty-pill" style={{ color: 'var(--wx-danger)' }}>{error}</div> : null}
        {loading ? <div className="wx-empty-pill">…</div> : null}
        {!loading && filtered.length === 0 ? <div className="wx-empty-pill">—</div> : null}
        <div className="wx-plugin-list">
          {filtered.map(plugin => {
            const meta = CATEGORY_META[plugin.category] || CATEGORY_META.productivity
            return (
              <div className={`wx-plugin-card ${plugin.enabled ? '' : 'is-off'}`} key={plugin.id}>
                <div className="wx-plugin-icon" style={{ background: meta.accent }}>
                  {ICON_BY_CATEGORY[plugin.category] || ICON_BY_CATEGORY.productivity}
                </div>
                <div className="wx-plugin-body">
                  <div className="wx-plugin-row1">
                    <div className="wx-plugin-name">{plugin.name}</div>
                    <label className="wx-switch">
                      <input type="checkbox" checked={plugin.enabled} onChange={() => toggle(plugin)} />
                      <span className="wx-switch-slider" />
                    </label>
                  </div>
                  <div className="wx-plugin-desc">{plugin.description}</div>
                  <div className="wx-plugin-meta">
                    <span className="wx-pill-mini brand">{meta.label}</span>
                    {plugin.builtin ? <span className="wx-pill-mini">{t('builtin') || 'Built-in'}</span> : null}
                    <span className={`wx-pill-mini ${plugin.enabled ? 'ok' : 'danger'}`}>{plugin.enabled ? t('enabled') || 'On' : t('disabled') || 'Off'}</span>
                  </div>
                </div>
                <button type="button" className="wx-icon-btn" aria-label={t('remove') || 'Remove'} onClick={() => remove(plugin)} title={t('remove') || 'Remove'}>
                  <svg viewBox="0 0 24 24"><path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M5 6l1 14a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2l1-14"/></svg>
                </button>
              </div>
            )
          })}
        </div>
      </div>

      {toast ? <div className="wx-toast">{toast}</div> : null}
    </section>
  )
}