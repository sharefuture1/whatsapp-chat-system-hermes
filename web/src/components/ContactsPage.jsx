import { useMemo, useState } from 'react'
import { useSettings } from '../settings'

function initials(name) {
  if (!name) return '?'
  const trimmed = name.trim()
  if (!trimmed) return '?'
  const parts = trimmed.split(/\s+/).filter(Boolean)
  if (parts.length === 1) return parts[0].slice(0, 2)
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase()
}

function avatarColor(name) {
  const colors = ['#5b8def', '#07c160', '#fa9d3b', '#f44c4c', '#9b59b6', '#16a085', '#e67e22', '#2ecc71']
  let h = 0
  for (const ch of name || '') h = (h * 31 + ch.charCodeAt(0)) >>> 0
  return colors[h % colors.length]
}

export default function ContactsPage({ conversations, onSelect }) {
  const { t } = useSettings()
  const [query, setQuery] = useState('')
  const sorted = useMemo(() => {
    const q = query.trim().toLowerCase()
    const list = [...conversations].sort((a, b) => (a.user_name || '').localeCompare(b.user_name || ''))
    if (!q) return list
    return list.filter(item =>
      (item.user_name || '').toLowerCase().includes(q) ||
      (item.user_id || '').toLowerCase().includes(q),
    )
  }, [conversations, query])
  return (
    <section className="wx-page wx-contacts-page">
      <div className="wx-page-header" style={{ paddingTop: 18, padding: '18px 14px 4px', display: 'grid', gap: 8 }}>
        <h2 style={{ fontSize: 22, fontWeight: 700, letterSpacing: -.3, margin: 0 }}>{t('tabContacts') || '通讯录'}</h2>
        <div className="wx-search" style={{ padding: 0 }}>
          <span className="wx-search-icon" aria-hidden="true">
            <svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/></svg>
          </span>
          <input
            value={query}
            onChange={e => setQuery(e.target.value)}
            placeholder={t('searchContactsPlaceholder') || '搜索联系人姓名或 ID'}
            style={{ width: '100%', background: 'var(--wx-panel-soft)', border: '1px solid transparent', borderRadius: 8, padding: '8px 10px 8px 32px', fontSize: 13, outline: 'none' }}
          />
        </div>
      </div>
      <div className="wx-cell-group">
        <div className="wx-cell-group-title">{t('tabContacts') || '通讯录'} · {sorted.length}</div>
        <div className="wx-section-list wx-card-list">
          {sorted.length === 0 ? <div className="wx-empty-pill">—</div> : null}
          {sorted.map(item => (
            <button key={item.user_id} type="button" className="wx-contact-row" onClick={() => onSelect(item.user_id)}>
              <div className="wx-avatar lg" style={{ background: avatarColor(item.user_name) }}>{initials(item.user_name)}</div>
              <div className="wx-contact-meta">
                <div className="wx-contact-name">{item.user_name}</div>
                <div className="wx-contact-subid">{item.user_id}</div>
              </div>
            </button>
          ))}
        </div>
      </div>
    </section>
  )
}