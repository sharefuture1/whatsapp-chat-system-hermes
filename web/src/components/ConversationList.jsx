import { useSettings } from '../settings'
import { fmtTime, fmtRelative } from '../format'

export default function ConversationList({
  conversations,
  selectedId,
  onSelect,
  query,
  onQueryChange,
  total,
  hasMore,
  onLoadMore,
  loadingMore,
  active,
  onOpenSettings,
  pinned,
  onTogglePin,
}) {
  const { t } = useSettings()
  return (
    <section className={`panel sidebar-panel${active ? ' is-active' : ''}`}>
      <div className="panel-header">
        <div>
          <h2>{t('navInbox')}</h2>
          <div className="subtle">
            {typeof total === 'number' ? `${total} ${t('hintTracked')}` : t('hintSearchContacts')}
          </div>
        </div>
        <button className="ghost-btn small-btn" onClick={onOpenSettings}>{t('settings')}</button>
      </div>
      <input
        className="search-box"
        value={query}
        onChange={e => onQueryChange(e.target.value)}
        placeholder={t('searchPlaceholder')}
      />
      {pinned && pinned.length > 0 ? (
        <div className="pinned-section">
          <div className="pinned-label">{t('pinned')}</div>
          {pinned.map(item => (
            <button
              key={`pin-${item.user_id}`}
              className={`conversation-item pinned${selectedId === item.user_id ? ' active' : ''}`}
              onClick={() => onSelect(item.user_id)}
            >
              <div className="conversation-topline">
                <div className="conversation-name">★ {item.user_name}</div>
                <button
                  className="pin-toggle"
                  aria-label={t('unpin')}
                  onClick={(e) => { e.stopPropagation(); onTogglePin(item.user_id) }}
                >×</button>
              </div>
              <div className="conversation-last">{item.last_message}</div>
            </button>
          ))}
        </div>
      ) : null}
      <div className="conversation-list">
        {conversations.length === 0 ? (
          <div className="empty-state subtle">{t('noConversations')}</div>
        ) : null}
        {conversations.map(item => (
          <button
            key={item.user_id}
            className={`conversation-item${selectedId === item.user_id ? ' active' : ''}`}
            onClick={() => onSelect(item.user_id)}
          >
            <div className="conversation-topline">
              <div className="conversation-name">{item.user_name}</div>
              <span className={`pill ${item.priority === 'high' ? 'danger' : 'ok'}`}>{item.priority}</span>
            </div>
            <div className="conversation-meta">{item.user_id}</div>
            <div className="conversation-stats">
              {(item.languages || []).join(' / ') || 'Unknown'} · {item.message_count} msgs · {fmtRelative(item.last_timestamp)}
            </div>
            <div className="conversation-last">{item.last_message}</div>
            <div className="conversation-actions">
              <span className="conversation-time">{fmtTime(item.last_timestamp)}</span>
              <button
                className="pin-toggle"
                aria-label={pinned?.find(p => p.user_id === item.user_id) ? t('unpin') : t('pin')}
                onClick={(e) => { e.stopPropagation(); onTogglePin(item.user_id) }}
              >
                {pinned?.find(p => p.user_id === item.user_id) ? '★' : '☆'}
              </button>
            </div>
          </button>
        ))}
        {hasMore ? (
          <button className="ghost-btn load-more-btn" onClick={onLoadMore} disabled={loadingMore}>
            {loadingMore ? t('loading') : t('loadMore')}
          </button>
        ) : null}
      </div>
    </section>
  )
}
