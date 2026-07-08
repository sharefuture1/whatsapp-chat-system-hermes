import { useEffect, useState } from 'react'
import { useSettings } from '../settings'

export default function SettingsPanel({ open, onClose, settings, channels, onSave, saving }) {
  const { t } = useSettings()
  const [draftChannels, setDraftChannels] = useState(channels)
  const [reply, setReply] = useState(settings?.reply || {})
  const [ui, setUi] = useState(settings?.ui || {})
  const [password, setPassword] = useState('')
  const [tab, setTab] = useState('reply')

  useEffect(() => {
    if (!open) return
    setDraftChannels(channels)
    setReply(settings?.reply || {})
    setUi(settings?.ui || {})
    setPassword('')
  }, [open, channels, settings])

  useEffect(() => {
    if (!open) return
    const onKey = e => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) return null

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
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label={t('settings')} onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <h2>{t('settings')}</h2>
          <button className="icon-btn" aria-label={t('dismiss')} onClick={onClose}>
            <span aria-hidden="true">✕</span>
          </button>
        </div>
        <div className="modal-tabs" role="tablist">
          <button role="tab" aria-selected={tab==='reply'} className={`tab ${tab==='reply' ? 'active' : ''}`} onClick={() => setTab('reply')}>{t('replyPolicy')}</button>
          <button role="tab" aria-selected={tab==='ui'} className={`tab ${tab==='ui' ? 'active' : ''}`} onClick={() => setTab('ui')}>{t('uiBehavior')}</button>
          <button role="tab" aria-selected={tab==='channels'} className={`tab ${tab==='channels' ? 'active' : ''}`} onClick={() => setTab('channels')}>{t('channels')}</button>
          <button role="tab" aria-selected={tab==='security'} className={`tab ${tab==='security' ? 'active' : ''}`} onClick={() => setTab('security')}>{t('security')}</button>
        </div>
        <div className="modal-body">
          {tab === 'reply' && (
            <div className="settings-section">
              <h3>{t('replyPolicy')}</h3>
              <div className="settings-grid">
                <label>
                  <span>{t('mode')}</span>
                  <select value={reply.default_mode || 'direct'} onChange={e => setReply(prev => ({ ...prev, default_mode: e.target.value }))}>
                    <option value="direct">{t('modeDirect')}</option>
                    <option value="smart">{t('modeSmart')}</option>
                    <option value="translate">{t('modeTranslate')}</option>
                  </select>
                </label>
                <label><span>Smart max length</span><input type="number" value={reply.smart_max_length || 40} onChange={e => setReply(prev => ({ ...prev, smart_max_length: Number(e.target.value) || 40 }))} /></label>
                <label><span>Translate max length</span><input type="number" value={reply.translate_max_length || 60} onChange={e => setReply(prev => ({ ...prev, translate_max_length: Number(e.target.value) || 60 }))} /></label>
                <label><span>Preview debounce ms</span><input type="number" value={reply.preview_debounce_ms || 320} onChange={e => setReply(prev => ({ ...prev, preview_debounce_ms: Number(e.target.value) || 320 }))} /></label>
                <label className="checkbox"><input type="checkbox" checked={!!reply.allow_fallback} onChange={e => setReply(prev => ({ ...prev, allow_fallback: e.target.checked }))} />Allow fallback</label>
                <label className="checkbox"><input type="checkbox" checked={!!reply.prefer_detected_language} onChange={e => setReply(prev => ({ ...prev, prefer_detected_language: e.target.checked }))} />Prefer detected language</label>
              </div>
            </div>
          )}
          {tab === 'ui' && (
            <div className="settings-section">
              <h3>{t('uiBehavior')}</h3>
              <div className="settings-grid">
                <label><span>Auto refresh seconds</span><input type="number" value={ui.auto_refresh_seconds || 10} onChange={e => setUi(prev => ({ ...prev, auto_refresh_seconds: Number(e.target.value) || 10 }))} /></label>
                <label className="checkbox"><input type="checkbox" checked={!!ui.show_preview_before_send} onChange={e => setUi(prev => ({ ...prev, show_preview_before_send: e.target.checked }))} />Show preview before send</label>
              </div>
            </div>
          )}
          {tab === 'channels' && (
            <div className="settings-section">
              <h3>{t('channels')}</h3>
              <div className="channels-grid">
                {draftChannels.map((channel, idx) => (
                  <div className="channel-card" key={channel.id}>
                    <div className="channel-card-header">
                      <strong>{channel.name}</strong>
                      <span className={`pill ${channel.enabled ? 'ok' : 'muted'}`}>{channel.enabled ? 'Enabled' : 'Disabled'}</span>
                    </div>
                    <label><span>Channel name</span><input value={channel.name} onChange={e => updateField(idx, 'name', e.target.value)} /></label>
                    <label><span>Platform</span><input value={channel.platform} onChange={e => updateField(idx, 'platform', e.target.value)} /></label>
                    <label><span>Target</span><input value={channel.target} onChange={e => updateField(idx, 'target', e.target.value)} /></label>
                    <label><span>Message kinds</span><input value={(channel.kinds || []).join(', ')} onChange={e => updateKinds(idx, e.target.value)} /></label>
                    <label className="checkbox"><input type="checkbox" checked={channel.enabled} onChange={e => updateField(idx, 'enabled', e.target.checked)} />Enable this channel</label>
                  </div>
                ))}
              </div>
            </div>
          )}
          {tab === 'security' && (
            <div className="settings-section">
              <h3>{t('security')}</h3>
              <div className="settings-grid">
                <label><span>{t('newPassword')}</span><input type="password" value={password} onChange={e => setPassword(e.target.value)} autoComplete="new-password" /></label>
              </div>
              <p className="subtle">{t('newPasswordHelp')}</p>
            </div>
          )}
        </div>
        <div className="modal-footer">
          <button className="ghost-btn" onClick={onClose}>{t('back')}</button>
          <button onClick={save} disabled={saving}>{saving ? t('saving') : t('save')}</button>
        </div>
      </div>
    </div>
  )
}
