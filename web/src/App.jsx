import { useEffect, useMemo, useState } from 'react'

const API = '/api'
const PASSWORD_PLACEHOLDER = 'test?9'

function apiFetch(path, options = {}, token = '') {
  const headers = { ...(options.headers || {}) }
  if (token) headers['x-session-token'] = token
  return fetch(`${API}${path}`, { ...options, headers })
}

function fmtTime(ts) {
  if (!ts) return '-'
  const d = new Date(ts * 1000)
  return d.toLocaleString()
}

function StatCard({ label, value, hint }) {
  return (
    <div className="stat-card">
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
      {hint ? <div className="stat-hint">{hint}</div> : null}
    </div>
  )
}

function LoginScreen({ onLogin, error, loading }) {
  const [password, setPassword] = useState('')
  return (
    <div className="login-shell">
      <div className="login-card">
        <div className="eyebrow">Secure Access</div>
        <h1>Operator Login</h1>
        <div className="subtle">Enter the console password to access conversations and controls.</div>
        <input type="password" value={password} onChange={e => setPassword(e.target.value)} placeholder={PASSWORD_PLACEHOLDER} />
        {error ? <div className="error-text">{error}</div> : null}
        <button disabled={loading || !password} onClick={() => onLogin(password)}>{loading ? 'Signing in...' : 'Sign in'}</button>
      </div>
    </div>
  )
}

function TopBar({ health, onRunJob, runningJob, onLogout }) {
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

function SettingsPanel({ settings, channels, onSave, saving }) {
  const [draftChannels, setDraftChannels] = useState(channels)
  const [reply, setReply] = useState(settings?.reply || {})
  const [ui, setUi] = useState(settings?.ui || {})
  const [password, setPassword] = useState('')

  useEffect(() => setDraftChannels(channels), [channels])
  useEffect(() => {
    setReply(settings?.reply || {})
    setUi(settings?.ui || {})
  }, [settings])

  const updateField = (index, key, value) => {
    setDraftChannels(prev => prev.map((item, i) => i === index ? { ...item, [key]: value } : item))
  }

  const updateKinds = (index, value) => {
    setDraftChannels(prev => prev.map((item, i) => i === index ? { ...item, kinds: value.split(',').map(s => s.trim()).filter(Boolean) } : item))
  }

  const save = () => onSave({
    channels: draftChannels,
    web_settings: { reply, ui, message_ops: settings?.message_ops || {} },
    password: password || null,
  }, () => setPassword(''))

  return (
    <section className="panel elevated luxury-panel">
      <div className="panel-header tight">
        <div>
          <h2>System Settings</h2>
          <div className="subtle">Core behavior, security, reply policy, and delivery channels.</div>
        </div>
        <button onClick={save} disabled={saving}>{saving ? 'Saving...' : 'Save Settings'}</button>
      </div>

      <div className="settings-section">
        <h3>Reply Policy</h3>
        <div className="settings-grid">
          <label>Default mode<select value={reply.default_mode || 'direct'} onChange={e => setReply(prev => ({ ...prev, default_mode: e.target.value }))}><option value="direct">Direct</option><option value="smart">Smart</option><option value="translate">Translate</option></select></label>
          <label>Smart max length<input type="number" value={reply.smart_max_length || 40} onChange={e => setReply(prev => ({ ...prev, smart_max_length: Number(e.target.value) || 40 }))} /></label>
          <label>Translate max length<input type="number" value={reply.translate_max_length || 60} onChange={e => setReply(prev => ({ ...prev, translate_max_length: Number(e.target.value) || 60 }))} /></label>
          <label>Preview debounce ms<input type="number" value={reply.preview_debounce_ms || 320} onChange={e => setReply(prev => ({ ...prev, preview_debounce_ms: Number(e.target.value) || 320 }))} /></label>
          <label className="checkbox"><input type="checkbox" checked={!!reply.allow_fallback} onChange={e => setReply(prev => ({ ...prev, allow_fallback: e.target.checked }))} />Allow fallback</label>
          <label className="checkbox"><input type="checkbox" checked={!!reply.prefer_detected_language} onChange={e => setReply(prev => ({ ...prev, prefer_detected_language: e.target.checked }))} />Prefer detected language</label>
        </div>
      </div>

      <div className="settings-section">
        <h3>UI Behavior</h3>
        <div className="settings-grid">
          <label>Auto refresh seconds<input type="number" value={ui.auto_refresh_seconds || 10} onChange={e => setUi(prev => ({ ...prev, auto_refresh_seconds: Number(e.target.value) || 10 }))} /></label>
          <label className="checkbox"><input type="checkbox" checked={!!ui.show_preview_before_send} onChange={e => setUi(prev => ({ ...prev, show_preview_before_send: e.target.checked }))} />Show preview before send</label>
          <label>New password<input type="password" value={password} onChange={e => setPassword(e.target.value)} placeholder={PASSWORD_PLACEHOLDER} /></label>
        </div>
      </div>

      <div className="settings-section">
        <h3>Admin Delivery Channels</h3>
        <div className="channels-grid">
          {draftChannels.map((channel, idx) => (
            <div className="channel-card" key={channel.id}>
              <div className="channel-card-header">
                <strong>{channel.name}</strong>
                <span className={`pill ${channel.enabled ? 'ok' : 'muted'}`}>{channel.enabled ? 'Enabled' : 'Disabled'}</span>
              </div>
              <label>Channel name<input value={channel.name} onChange={e => updateField(idx, 'name', e.target.value)} /></label>
              <label>Platform<input value={channel.platform} onChange={e => updateField(idx, 'platform', e.target.value)} /></label>
              <label>Target<input value={channel.target} onChange={e => updateField(idx, 'target', e.target.value)} /></label>
              <label>Message kinds<input value={(channel.kinds || []).join(', ')} onChange={e => updateKinds(idx, e.target.value)} /></label>
              <label className="checkbox"><input type="checkbox" checked={channel.enabled} onChange={e => updateField(idx, 'enabled', e.target.checked)} />Enable this channel</label>
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}

function ConversationList({ conversations, selectedId, onSelect, query, onQueryChange }) {
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

function MemorySummary({ detail }) {
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

function ReplyPreview({ preview, loading }) {
  if (loading) {
    return <div className="reply-preview-card"><div className="subtle">Generating smart preview…</div></div>
  }
  if (!preview) return null
  return (
    <div className="reply-preview-card">
      <div className="reply-preview-topline">
        <span className="pill muted">{preview.mode}</span>
        <span className={`pill ${preview.used_fallback ? 'danger' : 'ok'}`}>{preview.used_fallback ? 'fallback' : 'model'}</span>
      </div>
      <div className="reply-preview-meta">Language: {preview.language || 'direct'}</div>
      <div className="reply-preview-message">{preview.message}</div>
    </div>
  )
}

function ConversationDetail({ detail, onReply, onHideMessage, onHideLatest, sending, sendingMeta, uiSettings }) {
  const [message, setMessage] = useState('')
  const [mode, setMode] = useState('direct')
  const [preview, setPreview] = useState(null)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [bulkCount, setBulkCount] = useState(3)

  useEffect(() => {
    setMessage('')
    setPreview(null)
    setMode(uiSettings?.reply?.default_mode || 'direct')
  }, [detail?.user_id, uiSettings])

  useEffect(() => {
    if (!detail || !message.trim()) {
      setPreview(null)
      setPreviewLoading(false)
      return
    }
    if (mode === 'direct' || !uiSettings?.ui?.show_preview_before_send) {
      setPreview({ mode: 'direct', language: 'direct', message, used_fallback: false })
      setPreviewLoading(false)
      return
    }
    const controller = new AbortController()
    const timer = setTimeout(async () => {
      setPreviewLoading(true)
      try {
        const res = await apiFetch('/reply', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ target: detail.user_id, message, mode, preview_only: true }),
          signal: controller.signal,
        }, uiSettings?.sessionToken)
        const data = await res.json()
        if (data?.rewrite) {
          setPreview({
            mode,
            language: data.rewrite.language,
            message: data.rewrite.message,
            used_fallback: data.rewrite.used_fallback,
          })
        }
      } catch {
      } finally {
        setPreviewLoading(false)
      }
    }, uiSettings?.reply?.preview_debounce_ms || 320)
    return () => {
      controller.abort()
      clearTimeout(timer)
      setPreviewLoading(false)
    }
  }, [detail, message, mode, uiSettings])

  if (!detail) {
    return <section className="panel workspace-panel empty-state luxury-panel"><h2>Select a conversation</h2><div className="subtle">The workspace shows messages, memory, and advanced reply tooling.</div></section>
  }

  const effectivePreview = mode === 'direct'
    ? { mode: 'direct', language: 'direct', message, used_fallback: false }
    : preview

  return (
    <section className="panel workspace-panel elevated luxury-panel">
      <div className="workspace-header">
        <div>
          <div className="eyebrow">Active conversation</div>
          <h2>{detail.user_name}</h2>
          <div className="subtle">{detail.user_id}</div>
        </div>
        <div className="workspace-tags">
          <span className="pill muted">{detail.profile_summary?.language_hint || 'Unknown'}</span>
          <span className={`pill ${detail.profile_summary?.priority === 'high' ? 'danger' : 'ok'}`}>{detail.profile_summary?.priority || 'normal'}</span>
        </div>
      </div>
      <div className="workspace-grid premium-grid">
        <div className="message-column">
          <div className="message-list">
            {detail.messages.map((msg, idx) => (
              <div key={`${msg.session_id}-${idx}`} className={`message ${msg.role} ${msg.hidden ? 'hidden-message' : ''}`}>
                <div className="message-topline">
                  <div className="message-role">{msg.role}</div>
                  <div className="message-time">{fmtTime(msg.timestamp)}</div>
                </div>
                <div className="message-content">{msg.hidden ? '[Hidden in admin console]' : msg.content}</div>
                {!msg.hidden ? <div className="message-actions"><button className="danger-btn small-btn" onClick={() => onHideMessage(msg.message_id || msg.timestamp)}>Hide</button></div> : null}
              </div>
            ))}
          </div>
          <div className="panel luxury-panel bulk-delete-panel">
            <h3>Quick Hide</h3>
            <div className="subtle">Current stack does not support true WhatsApp bilateral revoke. This hides messages in the admin console only.</div>
            <div className="bulk-delete-row">
              <input type="number" min="1" value={bulkCount} onChange={e => setBulkCount(Number(e.target.value) || 1)} />
              <button className="danger-btn" onClick={() => onHideLatest(detail.user_id, bulkCount)}>Hide latest N</button>
            </div>
          </div>
        </div>
        <div className="composer-column">
          <div className="reply-box professional premium-box">
            <div className="reply-toolbar">
              <div>
                <h3>Reply composer</h3>
                <div className="subtle">Direct send, smart rewrite, or translate-first workflow.</div>
              </div>
              <select value={mode} onChange={e => setMode(e.target.value)}>
                <option value="direct">Direct</option>
                <option value="smart">Smart Rewrite</option>
                <option value="translate">Translate-first</option>
              </select>
            </div>
            <textarea value={message} onChange={e => setMessage(e.target.value)} placeholder="Write a response, preview it, then send..." />
            <ReplyPreview preview={effectivePreview && effectivePreview.message ? effectivePreview : null} loading={previewLoading} />
            <div className="reply-actions split">
              <div className="subtle">{sendingMeta ? `Last send: ${sendingMeta.mode}, language: ${sendingMeta.language}` : 'Preview before send to avoid duplicates'}</div>
              <button disabled={sending || !message.trim()} onClick={() => onReply(detail.user_id, message, mode, () => setMessage(''))}>{sending ? 'Sending...' : 'Send Reply'}</button>
            </div>
          </div>
          <MemorySummary detail={detail} />
        </div>
      </div>
    </section>
  )
}

function AliasPanel({ aliases }) {
  return (
    <section className="panel luxury-panel">
      <div className="panel-header tight">
        <div>
          <h2>Alias Directory</h2>
          <div className="subtle">Fast numeric shortcuts for operator workflows.</div>
        </div>
      </div>
      <div className="alias-list professional">
        {aliases.map(([alias, info]) => (
          <div key={alias} className="alias-item">
            <div><strong>{alias}</strong> · {info.name}</div>
            <div className="subtle">{info.chat_id}</div>
          </div>
        ))}
      </div>
    </section>
  )
}

export default function App() {
  const [sessionToken, setSessionToken] = useState(localStorage.getItem('chat-system-token') || '')
  const [loginError, setLoginError] = useState('')
  const [loginLoading, setLoginLoading] = useState(false)
  const [health, setHealth] = useState(null)
  const [dashboard, setDashboard] = useState(null)
  const [conversations, setConversations] = useState([])
  const [selectedId, setSelectedId] = useState('')
  const [detail, setDetail] = useState(null)
  const [settings, setSettings] = useState({ channels: [], aliases: {}, web_settings: {} })
  const [saving, setSaving] = useState(false)
  const [sending, setSending] = useState(false)
  const [sendingMeta, setSendingMeta] = useState(null)
  const [jobRunning, setJobRunning] = useState('')
  const [query, setQuery] = useState('')

  const authedFetch = (path, options = {}) => apiFetch(path, options, sessionToken)

  const handleLogin = async (password) => {
    setLoginLoading(true)
    setLoginError('')
    try {
      const resp = await fetch(`${API}/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ password }),
      })
      const data = await resp.json()
      if (!resp.ok) throw new Error(data.detail || 'Login failed')
      localStorage.setItem('chat-system-token', data.session_token)
      setSessionToken(data.session_token)
    } catch (e) {
      setLoginError(e.message)
    } finally {
      setLoginLoading(false)
    }
  }

  const logout = () => {
    localStorage.removeItem('chat-system-token')
    setSessionToken('')
    setDetail(null)
    setDashboard(null)
    setConversations([])
  }

  const loadBase = async () => {
    const [healthRes, dashboardRes, convRes, settingsRes] = await Promise.all([
      fetch(`${API}/health`).then(r => r.json()),
      authedFetch('/dashboard').then(r => r.json()),
      authedFetch('/conversations').then(r => r.json()),
      authedFetch('/settings').then(r => r.json()),
    ])
    setHealth(healthRes)
    setDashboard(dashboardRes)
    setConversations(convRes)
    setSettings({ ...settingsRes, sessionToken })
    if (!selectedId && convRes[0]) setSelectedId(convRes[0].user_id)
  }

  useEffect(() => {
    fetch(`${API}/health`).then(r => r.json()).then(setHealth)
  }, [])

  useEffect(() => {
    if (!sessionToken) return
    loadBase().catch(() => {
      logout()
    })
  }, [sessionToken])

  useEffect(() => {
    if (!selectedId || !sessionToken) return
    authedFetch(`/conversations/${encodeURIComponent(selectedId)}`).then(r => r.json()).then(setDetail)
  }, [selectedId, sessionToken])

  const saveSettings = async (payload, done) => {
    setSaving(true)
    try {
      await authedFetch('/settings', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      await loadBase()
      done?.()
    } finally {
      setSaving(false)
    }
  }

  const sendReply = async (target, message, mode, done) => {
    setSending(true)
    try {
      const res = await authedFetch('/reply', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ target, message, mode, preview_only: false }),
      })
      const data = await res.json()
      setSendingMeta({ mode: data.mode, language: data.rewrite?.language || 'direct' })
      await loadBase()
      if (selectedId) {
        const detailRes = await authedFetch(`/conversations/${encodeURIComponent(selectedId)}`).then(r => r.json())
        setDetail(detailRes)
      }
      done?.()
    } finally {
      setSending(false)
    }
  }

  const hideMessage = async (messageId) => {
    await authedFetch('/messages/hide', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message_ids: [messageId] }),
    })
    if (selectedId) {
      const detailRes = await authedFetch(`/conversations/${encodeURIComponent(selectedId)}`).then(r => r.json())
      setDetail(detailRes)
    }
  }

  const hideLatest = async (userId, count) => {
    if (!detail?.messages?.length) return
    const ids = detail.messages.slice(-count).map(m => m.message_id || m.timestamp)
    await authedFetch('/messages/hide', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message_ids: ids }),
    })
    const detailRes = await authedFetch(`/conversations/${encodeURIComponent(userId)}`).then(r => r.json())
    setDetail(detailRes)
  }

  const runJob = async job => {
    setJobRunning(job)
    try {
      await authedFetch('/jobs/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ job }),
      })
      await loadBase()
      if (selectedId) {
        const detailRes = await authedFetch(`/conversations/${encodeURIComponent(selectedId)}`).then(r => r.json())
        setDetail(detailRes)
      }
    } finally {
      setJobRunning('')
    }
  }

  const aliases = useMemo(() => Object.entries(settings.aliases || {}), [settings.aliases])
  const filteredConversations = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return conversations
    return conversations.filter(item =>
      item.user_name?.toLowerCase().includes(q) ||
      item.user_id?.toLowerCase().includes(q) ||
      item.last_message?.toLowerCase().includes(q)
    )
  }, [conversations, query])

  const stats = dashboard?.stats || {}

  if (!sessionToken) {
    return <LoginScreen onLogin={handleLogin} error={loginError} loading={loginLoading} />
  }

  return (
    <div className="app-shell pro ultra-shell">
      <TopBar health={health} onRunJob={runJob} runningJob={jobRunning} onLogout={logout} />

      <section className="stats-grid premium-stats">
        <StatCard label="Total conversations" value={stats.total_conversations ?? '-'} hint="Tracked cross-channel user threads" />
        <StatCard label="High priority" value={stats.high_priority_conversations ?? '-'} hint="Needs closer human attention" />
        <StatCard label="Total messages" value={stats.total_messages ?? '-'} hint="Messages currently indexed" />
        <StatCard label="Active admin channels" value={stats.active_admin_channels ?? '-'} hint={(stats.channel_names || []).join(', ') || 'No active routes'} />
      </section>

      <main className="pro-grid premium-layout">
        <ConversationList conversations={filteredConversations} selectedId={selectedId} onSelect={setSelectedId} query={query} onQueryChange={setQuery} />
        <ConversationDetail detail={detail} onReply={sendReply} onHideMessage={hideMessage} onHideLatest={hideLatest} sending={sending} sendingMeta={sendingMeta} uiSettings={settings.web_settings} />
        <div className="side-stack pro-side">
          <SettingsPanel settings={settings.web_settings} channels={settings.channels || []} onSave={saveSettings} saving={saving} />
          <AliasPanel aliases={aliases} />
        </div>
      </main>
    </div>
  )
}
