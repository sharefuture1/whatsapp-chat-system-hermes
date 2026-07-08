import { useSettings } from '../settings'
import { fmtRelative } from '../format'

function initials(name) {
  if (!name) return '?'
  const trimmed = name.trim()
  if (!trimmed) return '?'
  const parts = trimmed.split(/\s+/).filter(Boolean)
  if (parts.length === 1) return parts[0].slice(0, 2)
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase()
}

function platformLabel(platform) {
  const value = String(platform || 'unknown').toLowerCase()
  const map = { whatsapp: 'WA', telegram: 'TG', slack: 'SL', discord: 'DC' }
  return map[value] || value.slice(0, 2).toUpperCase()
}

function avatarColor(name) {
  const colors = ['#5b8def', '#07c160', '#fa9d3b', '#f44c4c', '#9b59b6', '#16a085', '#e67e22', '#2ecc71']
  let h = 0
  for (const ch of name || '') h = (h * 31 + ch.charCodeAt(0)) >>> 0
  return colors[h % colors.length]
}

export default function ChatList({
  conversations,
  selectedId,
  onSelect,
  query,
  onQueryChange,
  total,
  hasMore,
  onLoadMore,
  loadingMore,
  pinned,
  onTogglePin,
  onOpenSettings,
  onChangeLanguage,
  onToggleTheme,
  language,
  languages,
  theme,
  onLogout,
  unread,
  autoTranslate,
  platformFilter,
  platformOptions,
  onPlatformFilterChange,
}) {
  const { t } = useSettings()
  return (
    <aside className="wx-sidebar">
      <div className="wx-sidebar-header">
        <h1>{t('appTitle')}</h1>
        <div className="wx-sidebar-actions">
          <select
            className="wx-icon-btn"
            value={language}
            onChange={e => onChangeLanguage(e.target.value)}
            aria-label={t('language')}
            style={{ padding: '0 4px', fontSize: 12 }}
          >
            {languages.map(l => <option key={l.code} value={l.code}>{l.label}</option>)}
          </select>
          <button className="wx-icon-btn" aria-label={t('theme')} onClick={onToggleTheme} title={t('theme')}>
            <span aria-hidden="true">{theme === 'light' ? '☾' : '☀'}</span>
          </button>
          <button className="wx-icon-btn" aria-label={t('settings')} onClick={onOpenSettings} title={t('settings')}>
            <span aria-hidden="true">⚙</span>
          </button>
          <button className="wx-icon-btn" aria-label={t('logout')} onClick={onLogout} title={t('logout')}>
            <span aria-hidden="true">⏻</span>
          </button>
        </div>
      </div>
      <div className="wx-search">
        <svg className="wx-search-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <circle cx="11" cy="11" r="7" />
          <path d="M20 20l-3.5-3.5" />
        </svg>
        <input value={query} onChange={e => onQueryChange(e.target.value)} placeholder={t('searchPlaceholder')} />
      </div>
      {platformOptions && platformOptions.length > 1 ? (
        <div className="wx-platform-filter">
          {platformOptions.map(platform => (
            <button key={platform} className={`wx-filter-chip ${platformFilter === platform ? 'active' : ''}`} onClick={() => onPlatformFilterChange(platform)}>
              {platform === 'all' ? 'ALL' : platformLabel(platform)}
            </button>
          ))}
        </div>
      ) : null}
      {pinned && pinned.length > 0 ? (
        <div className="wx-pinned-section">
          {pinned.map(item => (
            <button key={`pin-${item.user_id}`} className={`wx-list-item${selectedId === item.user_id ? ' active' : ''}`} onClick={() => onSelect(item.user_id)}>
              <div className="wx-avatar" style={{ background: avatarColor(item.user_name) }}>{initials(item.user_name)}</div>
              <div className="wx-list-text">
                <div className="wx-list-row1">
                  <div className="wx-list-name"><span className="wx-pin-star">★</span> <span className="wx-platform-badge">{platformLabel(item.platform)}</span> {item.user_name}</div>
                </div>
                <div className="wx-list-row2">
                  <div className="wx-list-preview">{item.last_message || '…'}</div>
                </div>
                {autoTranslate && item.last_message_translated ? <div className="wx-list-translation">{item.last_message_translated}</div> : null}
              </div>
            </button>
          ))}
        </div>
      ) : null}
      <div className="wx-list">
        {conversations.length === 0 ? <div className="wx-empty">{t('noConversations')}</div> : null}
        {conversations.map(item => {
          const count = unread?.[item.user_id] || 0
          return (
            <button key={item.user_id} className={`wx-list-item${selectedId === item.user_id ? ' active' : ''}`} onClick={() => onSelect(item.user_id)}>
              <div className="wx-avatar" style={{ background: avatarColor(item.user_name) }}>{initials(item.user_name)}</div>
              <div className="wx-list-text">
                <div className="wx-list-row1">
                  <div className="wx-list-name"><span className="wx-platform-badge">{platformLabel(item.platform)}</span> {item.user_name}</div>
                  <div className="wx-list-time">{fmtRelative(item.last_timestamp)}</div>
                </div>
                <div className="wx-list-row2">
                  <div className="wx-list-preview">{item.last_message || '…'}</div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                    {item.priority === 'high' ? <span className="wx-pill-mini danger">!</span> : null}
                    {item.message_count > 0 ? <span className="wx-pill-mini">{item.message_count}</span> : null}
                  </div>
                </div>
                {autoTranslate && item.last_message_translated ? <div className="wx-list-translation">{item.last_message_translated}</div> : null}
              </div>
              {count > 0 ? <span className={`unread-badge${count > 99 ? ' muted' : ''}`}>{count > 99 ? '99+' : count}</span> : null}
            </button>
          )
        })}
        {hasMore ? <div className="wx-loadmore"><button onClick={onLoadMore} disabled={loadingMore}>{loadingMore ? t('loading') : t('loadMore')}</button></div> : null}
      </div>
    </aside>
  )
}
