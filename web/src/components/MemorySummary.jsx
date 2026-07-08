export default function MemorySummary({ detail }) {
  return (
    <div className="memory-panel">
      <div className="memory-meta-grid">
        <div className="memory-meta-card">
          <span className="subtle">Priority</span>
          <strong>{detail?.profile_summary?.priority || 'normal'}</strong>
        </div>
        <div className="memory-meta-card">
          <span className="subtle">Language hint</span>
          <strong>{detail?.profile_summary?.language_hint || 'Unknown'}</strong>
        </div>
        <div className="memory-meta-card">
          <span className="subtle">Sessions</span>
          <strong>{detail?.session_ids?.length || 0}</strong>
        </div>
      </div>
      <div className="memory-box">
        <h3>Customer memory</h3>
        <pre>{detail?.memory_markdown || 'No memory file yet.'}</pre>
      </div>
    </div>
  )
}
