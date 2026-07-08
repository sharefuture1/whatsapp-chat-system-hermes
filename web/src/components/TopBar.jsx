export default function TopBar({ health, onRunJob, runningJob, onLogout }) {
  return (
    <header className="topbar">
      <div>
        <div className="eyebrow">Operations Console</div>
        <h1>Customer Messaging Command Center</h1>
        <div className="subtle">{health ? `Workspace: ${health.profile}` : 'Loading workspace...'}</div>
      </div>
      <div className="topbar-actions">
        <button className="ghost-btn" onClick={() => onRunJob('router')} disabled={!!runningJob}>{runningJob === 'router' ? 'Running...' : 'Run Router'}</button>
        <button className="ghost-btn" onClick={() => onRunJob('forward')} disabled={!!runningJob}>{runningJob === 'forward' ? 'Running...' : 'Run Forward'}</button>
        <button onClick={() => onRunJob('refresh-memory')} disabled={!!runningJob}>{runningJob === 'refresh-memory' ? 'Running...' : 'Refresh Memory'}</button>
        <button className="ghost-btn" onClick={onLogout}>Logout</button>
      </div>
    </header>
  )
}
