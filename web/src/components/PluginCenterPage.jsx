import { useEffect, useState } from 'react'
import { useSettings } from '../settings'
import { api } from '../api'
import { fetchPersonaCatalog } from '../personas'

const CATEGORY_META = {
  messaging: { key: 'categoryMessaging', accent: '#07c160' },
  productivity: { key: 'categoryProductivity', accent: '#5b8def' },
  memory: { key: 'categoryMemory', accent: '#9b59b6' },
  media: { key: 'categoryMedia', accent: '#fa9d3b' },
  analytics: { key: 'categoryAnalytics', accent: '#16a085' },
}

const ICON_BY_CATEGORY = {
  messaging: (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M4 5h16a1 1 0 0 1 1 1v11a1 1 0 0 1-1 1h-9l-4 3v-3H4a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1z" />
    </svg>
  ),
  productivity: (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M12 2v4M12 18v4M4 12H2M22 12h-2M5 5l3 3M16 16l3 3M5 19l3-3M16 8l3-3" />
      <circle cx="12" cy="12" r="4" />
    </svg>
  ),
  memory: (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M3 5a2 2 0 0 1 2-2h6v18H5a2 2 0 0 1-2-2zM21 5a2 2 0 0 0-2-2h-6v18h6a2 2 0 0 0 2-2zM12 3v18" />
    </svg>
  ),
  media: (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <rect x="3" y="5" width="18" height="14" rx="2" />
      <path d="M10 9l5 3-5 3z" />
    </svg>
  ),
  analytics: (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M4 20V10M10 20V4M16 20v-7M22 20H2" />
    </svg>
  ),
}

export default function PluginCenterPage({ onBack, onOpenScheduler, onOpenBroadcast }) {
  const { t } = useSettings()
  const [plugins, setPlugins] = useState([])
  const [personas, setPersonas] = useState({ items: [], available: false, plugin_enabled: true })
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState(null)
  const [filter, setFilter] = useState('all')

  const refresh = async ({ manual = false } = {}) => {
    if (manual) setRefreshing(true)
    setError(null)
    try {
      const [pluginData, personaCatalog] = await Promise.all([
        api.get('/v1/plugins'),
        fetchPersonaCatalog(),
      ])
      setPlugins(pluginData.items ?? [])
      setPersonas({
        items: personaCatalog.items,
        available: personaCatalog.available,
        plugin_enabled: personaCatalog.plugin_enabled,
      })
    } catch (e) {
      setError(e.message || t('error'))
    } finally {
      if (manual) setRefreshing(false)
    }
  }

  useEffect(() => {
    setLoading(true)
    refresh().finally(() => setLoading(false))
  }, [])

  const toggle = async plugin => {
    if (plugin.available === false) return
    try {
      await api.post('/v1/plugins/toggle', { plugin_id: plugin.id, enabled: !plugin.enabled })
      await refresh()
    } catch (e) {
      setError(e.message || t('error'))
    }
  }

  const remove = async plugin => {
    if (plugin.available === false || !plugin.enabled) return
    if (!window.confirm(`${t('removePluginConfirm')} (${plugin.name})`)) return
    try {
      await api.delete(`/v1/plugins/${plugin.id}`)
      await refresh()
    } catch (e) {
      setError(e.message || t('error'))
    }
  }

  const categories = ['all', ...Object.keys(CATEGORY_META)]
  const filtered = filter === 'all' ? plugins : plugins.filter(p => p.category === filter)
  const enabledCount = plugins.filter(p => p.enabled).length

  const renderToolLink = plugin => {
    if (plugin.id === 'schedule' && onOpenScheduler) {
      return (
        <button type="button" className="wx-inline-btn" onClick={onOpenScheduler}>
          {t('openToolCenter')}
        </button>
      )
    }
    if (plugin.id === 'broadcast' && onOpenBroadcast) {
      return (
        <button type="button" className="wx-inline-btn" onClick={onOpenBroadcast}>
          {t('openToolCenter')}
        </button>
      )
    }
    return null
  }

  return (
    <section className="wx-page wx-plugin-center-page">
      <header className="wx-account-page-header">
        <button className="wx-icon-btn" type="button" onClick={onBack} aria-label={t('back')}>
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m15 5-7 7 7 7" /></svg>
        </button>
        <h2>{t('pluginCenter')}</h2>
        <button
          type="button"
          className="wx-icon-btn"
          onClick={() => refresh({ manual: true })}
          aria-label={t('refresh')}
          disabled={refreshing}
        >
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M20 12a8 8 0 1 1-2.34-5.66" />
            <path d="M20 4v5h-5" />
          </svg>
        </button>
      </header>

      <div className="wx-cell-group wx-persona-library">
        <div className="wx-cell-group-title">{t('personaLibrary')}</div>
        {loading ? <div className="wx-empty-pill">{t('personaLoading')}</div> : null}
        {!loading && error ? (
          <div className="wx-empty-pill wx-discover-error">{t('personaLoadFailed')}</div>
        ) : null}
        {!loading && !error ? (
          <>
            <div className="wx-persona-library-status">
              {personas.available ? t('personaAvailable') : t('personaUnavailable')}
            </div>
            <div className="wx-persona-grid">
              {personas.items.map(persona => (
                <article className="wx-persona-card" key={persona.id}>
                  <strong>{persona.name}</strong>
                  <p>{persona.description}</p>
                  <button
                    type="button"
                    className="wx-inline-btn"
                    disabled={!personas.available}
                  >
                    {personas.available ? t('personaUse') : t('personaUnavailable')}
                  </button>
                </article>
              ))}
            </div>
          </>
        ) : null}
      </div>

      <div className="wx-cell-group">
        <div className="wx-cell-group-title">
          {t('pluginCenter')} · {enabledCount}/{plugins.length}
        </div>
        <div className="wx-plugin-filters">
          {categories.map(cat => (
            <button
              type="button"
              key={cat}
              className={`wx-filter-chip ${filter === cat ? 'active' : ''}`}
              onClick={() => setFilter(cat)}
            >
              {cat === 'all' ? t('all') : t(CATEGORY_META[cat].key)}
            </button>
          ))}
        </div>
        {error ? <div className="wx-empty-pill wx-discover-error">{t('pluginLoadFailed')}: {error}</div> : null}
        {loading ? <div className="wx-empty-pill">{t('loading')}…</div> : null}
        {!loading && !error && filtered.length === 0 ? <div className="wx-empty-pill">{t('pluginEmptyFor')}</div> : null}
        <div className="wx-plugin-list">
          {filtered.map(plugin => {
            const meta = CATEGORY_META[plugin.category] || CATEGORY_META.productivity
            const isAvailable = plugin.available !== false
            const isEnabled = isAvailable && plugin.enabled
            const statusLine = !isAvailable
              ? t('pluginUnavailableReason')
              : isEnabled
                ? plugin.status_when_on || t('pluginOperational')
                : t('statusOff')
            return (
              <div className={`wx-plugin-card ${isEnabled ? '' : 'is-off'}`} key={plugin.id}>
                <div className="wx-plugin-icon" style={{ background: meta.accent }}>
                  {ICON_BY_CATEGORY[plugin.category] || ICON_BY_CATEGORY.productivity}
                </div>
                <div className="wx-plugin-body">
                  <div className="wx-plugin-row1">
                    <div className="wx-plugin-name">{plugin.name}</div>
                    <label className={`wx-switch ${plugin.available === false ? 'is-disabled' : ''}`}>
                      <input
                        type="checkbox"
                        checked={!!plugin.enabled}
                        disabled={plugin.available === false}
                        onChange={() => toggle(plugin)}
                      />
                      <span className="wx-switch-slider" />
                    </label>
                  </div>
                  <div className="wx-plugin-desc">{plugin.description}</div>
                  <div className="wx-plugin-meta">
                    <span className="wx-pill-mini brand">{t(meta.key)}</span>
                    {plugin.builtin ? <span className="wx-pill-mini">{t('builtin')}</span> : null}
                    <span
                      className={`wx-pill-mini ${!isAvailable ? 'danger' : isEnabled ? 'ok' : 'muted'}`}
                    >
                      {!isAvailable
                        ? t('unavailable')
                        : isEnabled
                          ? t('enabled')
                          : t('disabled')}
                    </span>
                  </div>
                  <div className="wx-plugin-status subtle">{statusLine}</div>
                  {!isAvailable && plugin.unavailable_reason ? (
                    <p className="wx-plugin-reason">{plugin.unavailable_reason}</p>
                  ) : null}
                  {Array.isArray(plugin.hooks) && plugin.hooks.length ? (
                    <ul className="wx-plugin-hooks">
                      {plugin.hooks.map(hook => <li key={hook}><code>{hook}</code></li>)}
                    </ul>
                  ) : !isAvailable ? (
                    <p className="wx-plugin-reason subtle">{t('pluginHookEmpty')}</p>
                  ) : null}
                  {!isAvailable ? renderToolLink(plugin) : null}
                </div>
                {isEnabled ? (
                  <button
                    type="button"
                    className="wx-icon-btn"
                    aria-label={t('remove')}
                    onClick={() => remove(plugin)}
                    title={t('remove')}
                  >
                    <svg viewBox="0 0 24 24" aria-hidden="true">
                      <path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M5 6l1 14a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2l1-14" />
                    </svg>
                  </button>
                ) : null}
              </div>
            )
          })}
        </div>
      </div>
    </section>
  )
}
