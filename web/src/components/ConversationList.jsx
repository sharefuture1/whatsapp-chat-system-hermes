import { fmtTime } from '../format'

export default function ConversationList({ conversations, selectedId, onSelect, query, onQueryChange }) {
  return (
    <section className="panel sidebar-panel luxury-panel">
      <div className="panel-header sidebar-header">
        <div>
          <h2>Conversations</h2>
          <div className="subtle">Search contacts and inspect recent activity.</div>
        </div>
      </div>
      <input className="search-box" value={query} onChange={e => onQueryChange(e.target.value)} placeholder="Search by name / id / latest text" />
      <div className="conversation-list">
        {conversations.map(item => (
          <button key={item.user_id} className={`conversation-item ${selectedId === item.user_id ? 'active' : ''}`} onClick={() => onSelect(item.user_id)}>
            <div className="conversation-topline">
              <div className="conversation-name">{item.user_name}</div>
              <span className={`pill ${item.priority === 'high' ? 'danger' : 'ok'}`}>{item.priority}</span>
            </div>
            <div className="conversation-meta">{item.user_id}</div>
            <div className="conversation-stats">{item.languages?.join(' / ') || 'Unknown'} · {item.message_count} msgs</div>
            <div className="conversation-last">{item.last_message}</div>
            <div className="conversation-time">{fmtTime(item.last_timestamp)}</div>
          </button>
        ))}
      </div>
    </section>
  )
}
