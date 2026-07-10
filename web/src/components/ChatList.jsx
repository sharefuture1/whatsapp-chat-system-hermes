import { useRef, useState } from 'react'
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

const ACTION_WIDTH = 144
const SWIPE_THRESHOLD = 64
const DIRECTION_THRESHOLD = 8

const iconProps = {
  viewBox: '0 0 24 24',
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.8,
  strokeLinecap: 'round',
  strokeLinejoin: 'round',
  'aria-hidden': true,
}

const PinIcon = () => <svg {...iconProps}><path d="M12 17v5M8 3h8l-2 5 4 2-3 4H9l-3-4 4-2-2-5z" /></svg>
const TrashIcon = () => <svg {...iconProps}><path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M5 6l1 14a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2l1-14" /></svg>
const SettingsIcon = () => <svg {...iconProps}><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 0 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1 1.7 1.7 0 0 0-.3-1.8l-.1-.1A2 2 0 1 1 7 4.2l.1.1a1.7 1.7 0 0 0 1.8.3 1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1A2 2 0 1 1 19.6 7l-.1.1a1.7 1.7 0 0 0-.3 1.8 1.7 1.7 0 0 0 1.5 1h.1a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.3 1.1z" /></svg>
const SearchIcon = () => <svg {...iconProps}><circle cx="11" cy="11" r="7" /><path d="M20 20l-3.5-3.5" /></svg>
const EmptyChatIcon = () => <svg {...iconProps} className="wx-empty-svg"><path d="M4 5h16a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1h-9l-4 3v-3H4a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1z" /><path d="M8 10h8M8 13h5" /></svg>

function SwipeRow({ rowId, children, onPin, onDelete, pinned, t, isOpen, onRequestOpen, onRequestClose }) {
  const [dragX, setDragX] = useState(null)
  const [dragging, setDragging] = useState(false)
  const gesture = useRef(null)
  const suppressClickUntil = useRef(0)
  const offset = dragX === null ? (isOpen ? -ACTION_WIDTH : 0) : dragX
  const revealed = offset < -4 || isOpen

  const begin = (x, y, pointerType) => {
    gesture.current = { startX: x, startY: y, direction: 'undecided', pointerType }
    setDragging(false)
  }

  const move = (x, y) => {
    const current = gesture.current
    if (!current) return
    const deltaX = x - current.startX
    const deltaY = y - current.startY
    if (current.direction === 'undecided') {
      if (Math.max(Math.abs(deltaX), Math.abs(deltaY)) < DIRECTION_THRESHOLD) return
      current.direction = Math.abs(deltaX) > Math.abs(deltaY) * 1.2 ? 'horizontal' : 'vertical'
      if (current.direction === 'vertical') return
      onRequestOpen(rowId)
      setDragging(true)
    }
    if (current.direction !== 'horizontal') return
    const base = isOpen ? -ACTION_WIDTH : 0
    setDragX(Math.max(-ACTION_WIDTH, Math.min(0, base + deltaX)))
  }

  const finish = () => {
    const current = gesture.current
    if (!current) return
    if (current.direction === 'horizontal') {
      const shouldOpen = offset <= -SWIPE_THRESHOLD
      if (shouldOpen) onRequestOpen(rowId)
      else onRequestClose(rowId)
      suppressClickUntil.current = Date.now() + 350
    }
    gesture.current = null
    setDragX(null)
    setDragging(false)
  }

  const cancel = () => {
    gesture.current = null
    setDragX(null)
    setDragging(false)
  }

  const guardClick = e => {
    if (Date.now() < suppressClickUntil.current || isOpen) {
      e.preventDefault()
      e.stopPropagation()
      if (isOpen) onRequestClose(rowId)
    }
  }

  return (
    <div
      className={`wx-swipe-wrap${revealed ? ' is-revealed' : ''}${dragging ? ' is-dragging' : ''}`}
      onTouchStart={e => begin(e.touches[0].clientX, e.touches[0].clientY, 'touch')}
      onTouchMove={e => move(e.touches[0].clientX, e.touches[0].clientY)}
      onTouchEnd={finish}
      onTouchCancel={cancel}
      onMouseDown={e => { if (e.button === 0) begin(e.clientX, e.clientY, 'mouse') }}
      onMouseMove={e => move(e.clientX, e.clientY)}
      onMouseUp={finish}
      onMouseLeave={() => { if (gesture.current?.pointerType === 'mouse') finish() }}
    >
      <div className="wx-swipe-actions" aria-hidden={!revealed}>
        <button type="button" tabIndex={revealed ? 0 : -1} className={`wx-swipe-action pin ${pinned ? 'is-active' : ''}`} onClick={() => { onPin(); onRequestClose(rowId) }}>
          <PinIcon /><span>{pinned ? t('unpin') : t('pin')}</span>
        </button>
        <button type="button" tabIndex={revealed ? 0 : -1} className="wx-swipe-action danger" onClick={() => { onDelete(); onRequestClose(rowId) }}>
          <TrashIcon /><span>{t('delete')}</span>
        </button>
      </div>
      <div className="wx-swipe-content" style={{ transform: `translate3d(${offset}px,0,0)` }} onClickCapture={guardClick}>{children}</div>
    </div>
  )
}

export default function ChatList({ conversations, selectedId, selectedProfileMap, onSelect, query, onQueryChange, hasMore, onLoadMore, loadingMore, pinned, pinnedSet, onTogglePin, onDeleteChat, unread, autoTranslate, platformFilter, platformOptions, onPlatformFilterChange, onOpenSettings }) {
  const { t } = useSettings()
  const [openSwipeId, setOpenSwipeId] = useState(null)
  const showPlatformFilter = platformOptions && platformOptions.length > 1
  const isPinnedFn = userId => pinnedSet instanceof Set ? pinnedSet.has(userId) : Array.isArray(pinnedSet) ? pinnedSet.includes(userId) : Array.isArray(pinned) ? pinned.includes(userId) : false

  const renderRow = item => {
    const count = unread?.[item.user_id] || 0
    const remark = selectedProfileMap?.[item.user_id]?.remark || ''
    const displayName = remark || item.user_name
    const showName = remark ? item.user_name : ''
    const isPinned = item.pinned || isPinnedFn(item.user_id)
    return (
      <SwipeRow key={item.user_id} rowId={item.user_id} pinned={isPinned} t={t} isOpen={openSwipeId === item.user_id} onRequestOpen={setOpenSwipeId} onRequestClose={id => setOpenSwipeId(current => current === id ? null : current)} onPin={() => onTogglePin(item.user_id)} onDelete={() => onDeleteChat(item.user_id)}>
        <button type="button" className={`wx-list-item${selectedId === item.user_id ? ' active' : ''}`} onClick={() => onSelect(item.user_id)}>
          <div className="wx-avatar" style={{ background: avatarColor(item.user_name) }}>{initials(displayName)}</div>
          <div className="wx-list-text">
            <div className="wx-list-row1"><div className="wx-list-name"><span className="wx-platform-badge">{platformLabel(item.platform)}</span><span>{displayName}</span></div><div className="wx-list-time">{fmtRelative(item.last_timestamp)}</div></div>
            <div className="wx-list-row2"><div className="wx-list-preview">{showName ? `${showName} · ${item.last_message || '…'}` : (item.last_message || '…')}</div><div className="wx-list-row2-right">{isPinned ? <span className="wx-pin-star" aria-label={t('pin')}>★</span> : null}{item.priority === 'high' ? <span className="wx-pill-mini danger">!</span> : null}{item.muted ? <span className="wx-mute-dot" aria-label={t('muted') || 'muted'} /> : null}{count > 0 ? <span className="wx-unread-badge">{count > 99 ? '99+' : count}</span> : null}</div></div>
            {autoTranslate && item.last_message_translated ? <div className="wx-list-translation">{item.last_message_translated}</div> : null}
          </div>
        </button>
      </SwipeRow>
    )
  }

  const pinnedItems = conversations.filter(item => isPinnedFn(item.user_id) || item.pinned)
  const normalItems = conversations.filter(item => !isPinnedFn(item.user_id) && !item.pinned)

  return <aside className="wx-sidebar" onClick={e => { if (e.target.closest('.wx-sidebar-header,.wx-search,.wx-platform-filter')) setOpenSwipeId(null) }}>
    <div className="wx-sidebar-header"><h1>{t('tabChats')}</h1><div className="wx-sidebar-actions"><button type="button" className="wx-icon-btn" aria-label={t('settings')} onClick={onOpenSettings}><SettingsIcon /></button></div></div>
    <div className="wx-search"><span className="wx-search-icon" aria-hidden="true"><SearchIcon /></span><input value={query} onChange={e => onQueryChange(e.target.value)} placeholder={t('searchPlaceholder')} /></div>
    {showPlatformFilter ? <div className="wx-platform-filter">{platformOptions.map(platform => <button key={platform} type="button" className={`wx-filter-chip ${platformFilter === platform ? 'active' : ''}`} onClick={() => onPlatformFilterChange(platform)}>{platform === 'all' ? 'ALL' : platformLabel(platform)}</button>)}</div> : null}
    <div className="wx-list" onScroll={() => setOpenSwipeId(null)}>
      {pinnedItems.length > 0 ? <div className="wx-pinned-section">{pinnedItems.map(renderRow)}</div> : null}
      {conversations.length === 0 ? <div className="wx-empty"><EmptyChatIcon /><div className="wx-empty-state-row"><h3>{t('noConversations')}</h3><p>{t('noConversationsHint') || '暂无会话记录'}</p></div></div> : null}
      {normalItems.map(renderRow)}
      {hasMore ? <div className="wx-loadmore"><button type="button" onClick={onLoadMore} disabled={loadingMore}>{loadingMore ? t('loading') : t('loadMore')}</button></div> : null}
    </div>
  </aside>
}
