import { useState } from 'react'
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

const SWIPE_THRESHOLD = 80

function SwipeRow({ children, onPin, onDelete, pinned, t }) {
  const [dx, setDx] = useState(0)
  const [startX, setStartX] = useState(null)
  const [open, setOpen] = useState(false)

  const onTouchStart = e => {
    setStartX(e.touches[0].clientX)
    setOpen(false)
  }
  const onTouchMove = e => {
    if (startX === null) return
    const delta = e.touches[0].clientX - startX
    if (delta < 0) {
      const limited = Math.max(delta, -160)
      setDx(limited)
    } else if (open) {
      const limited = Math.min(delta, 160)
      setDx(limited - 140)
    } else {
      setDx(0)
    }
  }
  const onTouchEnd = () => {
    if (dx < -SWIPE_THRESHOLD) {
      setDx(-140)
      setOpen(true)
    } else {
      setDx(0)
      setOpen(false)
    }
    setStartX(null)
  }
  const onMouseDown = e => {
    setStartX(e.clientX)
    setOpen(false)
  }
  const onMouseMove = e => {
    if (startX === null) return
    const delta = e.clientX - startX
    if (delta < 0) {
      setDx(Math.max(delta, -160))
    } else if (open) {
      setDx(Math.min(delta, 160) - 140)
    }
  }
  const onMouseUp = () => {
    if (dx < -SWIPE_THRESHOLD) {
      setDx(-140)
      setOpen(true)
    } else {
      setDx(0)
      setOpen(false)
    }
    setStartX(null)
  }

  return (
    <div
      className="wx-swipe-wrap"
      style={{ transform: `translateX(${dx}px)` }}
      onTouchStart={onTouchStart}
      onTouchMove={onTouchMove}
      onTouchEnd={onTouchEnd}
      onMouseDown={onMouseDown}
      onMouseMove={onMouseMove}
      onMouseUp={onMouseUp}
      onMouseLeave={() => { if (startX !== null) onMouseUp() }}
    >
      <div className="wx-swipe-content">{children}</div>
      <div className="wx-swipe-actions">
        <button
          type="button"
          className={`wx-swipe-action pin ${pinned ? 'is-active' : ''}`}
          onClick={() => { onPin(); setDx(0); setOpen(false) }}
        >
          <svg viewBox="0 0 24 24"><path d="M12 17v5M8 3h8l-2 5 4 2-3 4H9l-3-4 4-2-2-5z"/></svg>
          <span>{pinned ? t('unpin') : t('pin')}</span>
        </button>
        <button
          type="button"
          className="wx-swipe-action danger"
          onClick={() => { onDelete(); setDx(0); setOpen(false) }}
        >
          <svg viewBox="0 0 24 24"><path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M5 6l1 14a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2l1-14"/></svg>
          <span>{t('delete')}</span>
        </button>
      </div>
    </div>
  )
}

const PlusIcon = () => (
  <svg viewBox="0 0 24 24"><path d="M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 0 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/></svg>
)

export default function ChatList({
  conversations,
  selectedId,
  selectedProfileMap,
  onSelect,
  query,
  onQueryChange,
  total,
  hasMore,
  onLoadMore,
  loadingMore,
  pinned,
  pinnedSet,
  onTogglePin,
  onDeleteChat,
  unread,
  autoTranslate,
  platformFilter,
  platformOptions,
  onPlatformFilterChange,
  onOpenSettings,
}) {
  const { t } = useSettings()
  const showPlatformFilter = platformOptions && platformOptions.length > 1
  const isPinnedFn = (userId) => {
    if (pinnedSet instanceof Set) return pinnedSet.has(userId)
    if (Array.isArray(pinnedSet)) return pinnedSet.includes(userId)
    if (Array.isArray(pinned)) return pinned.includes(userId)
    return false
  }
  const renderRow = (item) => {
    const count = unread?.[item.user_id] || 0
    const remark = selectedProfileMap?.[item.user_id]?.remark || ''
    const displayName = remark || item.user_name
    const showName = remark ? item.user_name : ''
    const isPinned = item.pinned || isPinnedFn(item.user_id)
    return (
      <SwipeRow
        key={item.user_id}
        pinned={isPinned}
        t={t}
        onPin={() => onTogglePin(item.user_id)}
        onDelete={() => onDeleteChat(item.user_id)}
      >
        <button
          type="button"
          className={`wx-list-item${selectedId === item.user_id ? ' active' : ''}`}
          onClick={() => onSelect(item.user_id)}
        >
          <div className="wx-avatar" style={{ background: avatarColor(item.user_name) }}>{initials(displayName)}</div>
          <div className="wx-list-text">
            <div className="wx-list-row1">
              <div className="wx-list-name">
                <span className="wx-platform-badge">{platformLabel(item.platform)}</span>
                <span>{displayName}</span>
              </div>
              <div className="wx-list-time">{fmtRelative(item.last_timestamp)}</div>
            </div>
            <div className="wx-list-row2">
              <div className="wx-list-preview">{showName ? `${showName} · ${item.last_message || '…'}` : (item.last_message || '…')}</div>
              <div className="wx-list-row2-right">
                {isPinned ? <span className="wx-pin-star" aria-label={t('pin')}>★</span> : null}
                {item.priority === 'high' ? <span className="wx-pill-mini danger">!</span> : null}
                {item.muted ? <span className="wx-mute-dot" aria-label={t('muted') || 'muted'} /> : null}
                {count > 0 ? <span className="wx-unread-badge">{count > 99 ? '99+' : count}</span> : null}
              </div>
            </div>
            {autoTranslate && item.last_message_translated ? <div className="wx-list-translation">{item.last_message_translated}</div> : null}
          </div>
        </button>
      </SwipeRow>
    )
  }
  return (
    <aside className="wx-sidebar">
      <div className="wx-sidebar-header">
        <h1>{t('tabChats')}</h1>
        <div className="wx-sidebar-actions">
          <button type="button" className="wx-icon-btn" aria-label={t('settings')} onClick={onOpenSettings}><PlusIcon /></button>
        </div>
      </div>
      <div className="wx-search">
        <span className="wx-search-icon" aria-hidden="true">
          <svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/></svg>
        </span>
        <input value={query} onChange={e => onQueryChange(e.target.value)} placeholder={t('searchPlaceholder')} />
      </div>
      {showPlatformFilter ? (
        <div className="wx-platform-filter">
          {platformOptions.map(platform => (
            <button key={platform} type="button" className={`wx-filter-chip ${platformFilter === platform ? 'active' : ''}`} onClick={() => onPlatformFilterChange(platform)}>
              {platform === 'all' ? 'ALL' : platformLabel(platform)}
            </button>
          ))}
        </div>
      ) : null}
      {(() => {
        const pinnedItems = conversations.filter(item => isPinnedFn(item.user_id) || item.pinned)
        const normalItems = conversations.filter(item => !isPinnedFn(item.user_id) && !item.pinned)
        return (
          <>
            {pinnedItems.length > 0 ? (
              <div className="wx-pinned-section">
                {pinnedItems.map(renderRow)}
              </div>
            ) : null}
          </>
        )
      })()}
      <div className="wx-list">
        {conversations.length === 0 ? (
          <div className="wx-empty">
            <div className="wx-empty-illustration">💬</div>
            <div className="wx-empty-state-row">
              <h3>{t('noConversations')}</h3>
              <p>{t('noConversationsHint') || '暂无会话记录'}</p>
            </div>
          </div>
        ) : null}
        {(() => {
          const normalItems = conversations.filter(item => !isPinnedFn(item.user_id) && !item.pinned)
          return normalItems.map(renderRow)
        })()}
        {hasMore ? <div className="wx-loadmore"><button type="button" onClick={onLoadMore} disabled={loadingMore}>{loadingMore ? t('loading') : t('loadMore')}</button></div> : null}
      </div>
    </aside>
  )
}