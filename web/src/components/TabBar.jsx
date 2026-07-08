import { useSettings } from '../settings'

const TABS = [
  { id: 'chats', key: 'tabChats', icon: '💬' },
  { id: 'contacts', key: 'tabContacts', icon: '👥' },
  { id: 'discover', key: 'tabDiscover', icon: '🧭' },
  { id: 'me', key: 'tabMe', icon: '👤' },
]

export default function TabBar({ activeTab, onChange, unreadChats }) {
  const { t } = useSettings()
  return (
    <nav className="wx-tabbar" role="tablist">
      {TABS.map(tab => (
        <button key={tab.id} className={`wx-tabbar-item ${activeTab === tab.id ? 'active' : ''}`} onClick={() => onChange(tab.id)} role="tab" aria-selected={activeTab === tab.id}>
          <span className="wx-tabbar-icon" aria-hidden="true">{tab.icon}</span>
          <span className="wx-tabbar-label">{t(tab.key)}</span>
          {tab.id === 'chats' && unreadChats > 0 ? <span className="wx-tabbar-badge">{unreadChats > 99 ? '99+' : unreadChats}</span> : null}
        </button>
      ))}
    </nav>
  )
}
