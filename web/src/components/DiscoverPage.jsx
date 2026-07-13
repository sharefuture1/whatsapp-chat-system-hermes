import { useEffect, useState } from 'react'
import { useSettings } from '../settings'
import { api } from '../api'
import { fetchPersonaCatalog } from '../personas'

export default function DiscoverPage({ dashboard, channels, conversations }) {
  const { t } = useSettings()
  const [personas, setPersonas] = useState({ items: [], available: false, plugin_enabled: true })
  const [stats, setStats] = useState(dashboard?.stats ?? {})
  const [pluginsEnabled, setPluginsEnabled] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const refresh = async () => {
    setError(null)
    try {
      const [summary, personaCatalog] = await Promise.all([
        api.get('/dashboard').catch(() => null),
        fetchPersonaCatalog(),
      ])
      if (summary?.stats) {
        setStats(summary.stats)
        if (typeof summary.plugins_enabled === 'number') {
          setPluginsEnabled(summary.plugins_enabled)
        }
      }
      setPersonas({
        items: personaCatalog.items,
        available: personaCatalog.available,
        plugin_enabled: personaCatalog.plugin_enabled,
      })
    } catch (e) {
      setError(e.message || t('error'))
    }
  }

  useEffect(() => {
    setLoading(true)
    refresh().finally(() => setLoading(false))
  }, [])

  const overviewCards = [
    { label: t('totalConversations'), value: stats.total_conversations ?? '—', accent: '#5b8def' },
    { label: t('highPriority'), value: stats.high_priority_conversations ?? '—', accent: '#fa5151' },
    { label: t('totalMessages'), value: stats.total_messages ?? '—', accent: '#07c160' },
    { label: t('activeChannels'), value: channels?.length ?? 0, accent: '#fa9d3b' },
    { label: t('contactsCount'), value: conversations?.length ?? '—', accent: '#16a085' },
  ]

  return (
    <section className="wx-page wx-discover-page">
      <header className="wx-page-header wx-discover-header">
        <h2>{t('tabDiscover')}</h2>
        <p>{t('discoverSubtitle')}</p>
      </header>

      <div className="wx-cell-group">
        <div className="wx-cell-group-title">{t('overview')}</div>
        <div className="wx-discover-grid">
          {overviewCards.map(card => (
            <div className="wx-discover-card" key={card.label} style={{ borderTop: `3px solid ${card.accent}` }}>
              <div className="wx-info-title">{card.label}</div>
              <div className="wx-info-value">{card.value}</div>
            </div>
          ))}
        </div>
      </div>

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
    </section>
  )
}
