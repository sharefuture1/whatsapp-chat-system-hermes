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
  const sorted = [...conversations].sort((a, b) => (a.user_name || '').localeCompare(b.user_name || ''))
  return (
    <section className="wx-page">
      <div className="wx-page-header"><h2>{t('tabContacts') || '通讯录'}</h2></div>
      <div className="wx-section-list">
        {sorted.map(item => (
          <button key={item.user_id} className="wx-contact-row" onClick={() => onSelect(item.user_id)}>
            <div className="wx-avatar lg" style={{ background: avatarColor(item.user_name) }}>{initials(item.user_name)}</div>
            <div className="wx-contact-name">{item.user_name}</div>
          </button>
        ))}
      </div>
    </section>
  )
}
