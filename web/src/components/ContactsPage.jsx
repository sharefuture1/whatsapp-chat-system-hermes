import { useMemo, useState } from 'react'
import { useSettings } from '../settings'
import { filterInbox } from '../inboxModel'

function initials(name) {
  const text = String(name || '?').trim()
  const parts = text.split(/\s+/).filter(Boolean)
  return parts.length > 1 ? `${parts[0][0]}${parts.at(-1)[0]}`.toUpperCase() : text.slice(0, 2)
}

function avatarColor(name) {
  const colors = ['#576b95', '#07c160', '#fa9d3b', '#f44c4c', '#9b59b6', '#16a085']
  let hash = 0
  for (const char of String(name || '')) hash = (hash * 31 + char.charCodeAt(0)) >>> 0
  return colors[hash % colors.length]
}

function platformLabel(platform) {
  if (platform === 'whatsapp') return 'WA'
  return String(platform || '').slice(0, 3).toUpperCase()
}

export default function ContactsPage({ contacts = [], accounts = [], onSelect }) {
  const { t } = useSettings()
  const [query, setQuery] = useState('')
  const [platform, setPlatform] = useState('all')
  const [accountId, setAccountId] = useState('all')
  const platforms = useMemo(() => ['all', ...new Set(contacts.map(item => item.platform).filter(Boolean))], [contacts])
  const visibleAccounts = useMemo(() => accounts.filter(item => platform === 'all' || item.platform === platform), [accounts, platform])
  const visible = useMemo(() => {
    const q = query.trim().toLowerCase()
    return filterInbox(contacts, { platform, accountId })
      .filter(item => !q || [item.user_name, item.remote_jid, item.account_name, item.account_label, item.remark].some(value => String(value || '').toLowerCase().includes(q)))
      .sort((a, b) => String(a.user_name || '').localeCompare(String(b.user_name || ''), 'zh-CN'))
  }, [contacts, query, platform, accountId])
  const grouped = useMemo(() => {
    const map = new Map()
    for (const item of visible) {
      const key = item.account_id
      if (!map.has(key)) map.set(key, { account: accounts.find(account => account.id === key), items: [] })
      map.get(key).items.push(item)
    }
    return [...map.values()]
  }, [visible, accounts])

  return <section className="wx-page wx-contacts-page">
    <header className="wx-contacts-header">
      <div><h2>{t('tabContacts') || '通讯录'}</h2><p>{t('multiAccountContactsHint') || '跨平台、多账号联系人'}</p></div>
      <span>{visible.length}</span>
    </header>
    <div className="wx-contact-controls">
      <div className="wx-platform-filter">{platforms.map(item => <button type="button" key={item} className={`wx-filter-chip ${platform === item ? 'active' : ''}`} onClick={() => { setPlatform(item); setAccountId('all') }}>{item === 'all' ? 'ALL' : platformLabel(item)}</button>)}</div>
      <div className="wx-account-tabs">
        <button type="button" className={`wx-account-tab ${accountId === 'all' ? 'active' : ''}`} onClick={() => setAccountId('all')}>{t('accountAll') || '全部账号'}</button>
        {visibleAccounts.map(account => <button type="button" className={`wx-account-tab ${accountId === account.id ? 'active' : ''}`} key={account.id} onClick={() => setAccountId(account.id)}><span>{account.label || account.name}</span><i className={account.status === 'online' ? 'online' : ''} /></button>)}
      </div>
      <div className="wx-search wx-contact-search"><span className="wx-search-icon"><svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/></svg></span><input value={query} onChange={event => setQuery(event.target.value)} placeholder={t('searchContactsPlaceholder') || '搜索联系人、账号或 ID'} /></div>
    </div>
    <div className="wx-contacts-scroll">
      {grouped.length === 0 ? <div className="wx-empty-pill">{t('noContacts') || '暂无联系人'}</div> : grouped.map(group => <section className="wx-contact-account-group" key={group.account?.id || group.items[0]?.account_id}>
        <div className="wx-contact-group-title"><span>{group.account?.label || group.items[0]?.account_label || 'WA'}</span><strong>{group.account?.name || group.items[0]?.account_name}</strong><em>{group.items.length}</em></div>
        <div className="wx-contact-list">{group.items.map(item => <button key={item.contact_key} type="button" className="wx-contact-row" disabled={!item.conversation_key} onClick={() => onSelect(item)}>
          <div className="wx-avatar" style={{ background: avatarColor(item.user_name) }}>{initials(item.user_name)}</div>
          <div className="wx-contact-meta"><div className="wx-contact-name">{item.user_name}</div><div className="wx-contact-subid"><span>{item.account_label}</span>{item.remote_jid || item.user_id}</div></div>
          <svg className="wx-cell-arrow" viewBox="0 0 24 24"><path d="M9 6l6 6-6 6"/></svg>
        </button>)}</div>
      </section>)}
    </div>
  </section>
}
