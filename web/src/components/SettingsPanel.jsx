import { useEffect, useState } from 'react'

export default function SettingsPanel({ settings, channels, onSave, saving }) {
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
          <label>New password<input type="password" value={password} onChange={e => setPassword(e.target.value)} placeholder="Leave empty to keep current" autoComplete="new-password" /></label>
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
