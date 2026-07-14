import { memo } from 'react'
import { useSettings } from '../settings'

const ChatIcon = () => (
  <svg viewBox="0 0 24 24"><path d="M4 5h16a1 1 0 0 1 1 1v11a1 1 0 0 1-1 1h-9l-4 3v-3H4a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1z"/></svg>
)
const ContactsIcon = () => (
  <svg viewBox="0 0 24 24"><circle cx="9" cy="9" r="3"/><path d="M3 19c0-3 3-5 6-5s6 2 6 5"/><circle cx="17" cy="8" r="2.4"/><path d="M14 14c2.5-.7 7 .6 7 4"/></svg>
)
const DiscoverIcon = () => (
  <svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M15 9l-2 6-6 2 2-6z"/></svg>
)
const MeIcon = () => (
  <svg viewBox="0 0 24 24"><circle cx="12" cy="8" r="4"/><path d="M4 20c0-3.5 4-6 8-6s8 2.5 8 6"/></svg>
)

const TABS = [
  { id: 'chats', key: 'tabChats', Icon: ChatIcon },
  { id: 'contacts', key: 'tabContacts', Icon: ContactsIcon },
  { id: 'discover', key: 'tabDiscover', Icon: DiscoverIcon },
  { id: 'me', key: 'tabMe', Icon: MeIcon },
]

function TabBar({ activeTab, onChange, unreadChats, hidden = false }) {
  const { t } = useSettings()
  return (
    <nav className={`wx-tab-bar${hidden ? ' is-chat-hidden' : ''}`} role="tablist">
      {TABS.map(({ id, key, Icon }) => (
        <button
          key={id}
          type="button"
          className={`wx-tab-btn ${activeTab === id ? 'active' : ''}`}
          onClick={() => onChange(id)}
          role="tab"
          aria-selected={activeTab === id}
        >
          <span aria-hidden="true"><Icon /></span>
          <span>{t(key)}</span>
          {id === 'chats' && unreadChats > 0 ? <span className="wx-tab-badge">{unreadChats > 99 ? '99+' : unreadChats}</span> : null}
        </button>
      ))}
    </nav>
  )
}

export default memo(TabBar)