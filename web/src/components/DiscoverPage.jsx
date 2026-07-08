import { useSettings } from '../settings'

export default function DiscoverPage({ dashboard, channels }) {
  const { t } = useSettings()
  const stats = dashboard?.stats || {}
  return (
    <section className="wx-page">
      <div className="wx-page-header"><h2>{t('tabDiscover') || '发现'}</h2></div>
      <div className="wx-card-grid">
        <div className="wx-info-card"><div className="wx-info-title">{t('totalConversations')}</div><div className="wx-info-value">{stats.total_conversations ?? '-'}</div></div>
        <div className="wx-info-card"><div className="wx-info-title">{t('highPriority')}</div><div className="wx-info-value">{stats.high_priority_conversations ?? '-'}</div></div>
        <div className="wx-info-card"><div className="wx-info-title">{t('totalMessages')}</div><div className="wx-info-value">{stats.total_messages ?? '-'}</div></div>
        <div className="wx-info-card"><div className="wx-info-title">{t('activeChannels')}</div><div className="wx-info-value">{channels?.length ?? 0}</div></div>
      </div>
    </section>
  )
}
