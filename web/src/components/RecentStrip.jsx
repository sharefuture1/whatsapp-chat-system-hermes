import { useSettings } from '../settings'
import { fmtRelative } from '../format'

export default function RecentStrip({ recent, onSelect, total }) {
  const { t } = useSettings()
  if (!recent || recent.length === 0) return null
  return (
    <section className="recent-strip">
      <div className="recent-strip-head">
        <h3>{t('recent')}</h3>
        {typeof total === 'number' ? <span className="subtle">{t('totalLabel')}: {total}</span> : null}
      </div>
      <div className="recent-strip-list">
        {recent.map(item => (
          <button key={`recent-${item.user_id}`} className="recent-card" onClick={() => onSelect(item.user_id)}>
            <div className="recent-card-topline">
              <div className="recent-card-name">{item.user_name}</div>
              <span className={`pill ${item.priority === 'high' ? 'danger' : 'ok'}`}>{item.priority}</span>
            </div>
            <div className="recent-card-msg">{item.last_message}</div>
            <div className="recent-card-meta">
              {item.message_count} msgs · {fmtRelative(item.last_timestamp)}
            </div>
          </button>
        ))}
      </div>
    </section>
  )
}
