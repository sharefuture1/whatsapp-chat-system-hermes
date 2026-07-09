import { useEffect, useState } from 'react'
import { useSettings } from '../settings'

const PLATFORM_OPTIONS = [
  { platform: 'whatsapp', label: 'WhatsApp', category: '聊天', method: '二维码', command: 'hermes -p <profile> whatsapp' },
  { platform: 'telegram', label: 'Telegram', category: '聊天', method: '手动配置', command: 'hermes -p <profile> telegram' },
  { platform: 'slack', label: 'Slack', category: '团队', method: '手动配置', command: 'hermes -p <profile> slack' },
  { platform: 'discord', label: 'Discord', category: '社区', method: '手动配置', command: 'hermes -p <profile> discord' },
]

function makeWorkspace(platform = 'whatsapp') {
  const id = `${platform}-${Date.now()}`
  return { id, label: `${platform} account`, platform, profile: id, profile_path: `/root/.hermes/profiles/${id}`, enabled: true, primary: false }
}

function commandFor(workspace) {
  const option = PLATFORM_OPTIONS.find(item => item.platform === workspace.platform) || PLATFORM_OPTIONS[0]
  return option.command.replace('<profile>', workspace.profile || workspace.id || workspace.platform)
}

export default function SettingsPanel({ open, onClose, settings, channels, onSave, saving }) {
  const { t } = useSettings()
  const [draftChannels, setDraftChannels] = useState(channels)
  const [reply, setReply] = useState(settings?.reply || {})
  const [ui, setUi] = useState(settings?.ui || {})
  const [messageOps, setMessageOps] = useState(settings?.message_ops || { auto_translate: true })
  const [workspaces, setWorkspaces] = useState(settings?.workspaces || [])
  const [password, setPassword] = useState('')
  const [tab, setTab] = useState('reply')

  useEffect(() => {
    if (!open) return
    setDraftChannels(channels)
    setReply(settings?.reply || {})
    setUi(settings?.ui || {})
    setMessageOps(settings?.message_ops || { auto_translate: true })
    setWorkspaces(settings?.workspaces || [])
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

  const updateWorkspace = (index, key, value) => {
    setWorkspaces(prev => prev.map((item, i) => i === index ? { ...item, [key]: value } : item))
  }

  const addWorkspace = (platform = 'whatsapp') => {
    setWorkspaces(prev => [...prev, makeWorkspace(platform)])
  }

  const removeWorkspace = (index) => {
    setWorkspaces(prev => prev.filter((_, i) => i !== index))
  }

  const save = () => onSave({
    channels: draftChannels,
    web_settings: { reply, ui, message_ops: messageOps, workspaces },
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
          <button role="tab" aria-selected={tab==='platforms'} className={`tab ${tab==='platforms' ? 'active' : ''}`} onClick={() => setTab('platforms')}>平台账号</button>
          <button role="tab" aria-selected={tab==='security'} className={`tab ${tab==='security' ? 'active' : ''}`} onClick={() => setTab('security')}>{t('security')}</button>
        </div>
        <div className="modal-body">
          {tab === 'reply' && (
            <div className="settings-section">
              <h3>{t('replyPolicy')}</h3>
              <div className="settings-grid">
                <label>
                  <span>{t('mode')}</span>
                  <select value={reply.default_mode || 'smart'} onChange={e => setReply(prev => ({ ...prev, default_mode: e.target.value }))}>
                    <option value="direct">{t('modeDirect')}</option>
                    <option value="smart">{t('modeSmart')}</option>
                    <option value="translate">{t('modeTranslate')}</option>
                  </select>
                </label>
                <label><span>{t('settingSmartMax')}</span><input type="number" value={reply.smart_max_length || 40} onChange={e => setReply(prev => ({ ...prev, smart_max_length: Number(e.target.value) || 40 }))} /></label>
                <label><span>{t('settingTranslateMax')}</span><input type="number" value={reply.translate_max_length || 60} onChange={e => setReply(prev => ({ ...prev, translate_max_length: Number(e.target.value) || 60 }))} /></label>
                <label><span>{t('settingPreviewDebounce')}</span><input type="number" value={reply.preview_debounce_ms || 320} onChange={e => setReply(prev => ({ ...prev, preview_debounce_ms: Number(e.target.value) || 320 }))} /></label>
                <label className="checkbox"><input type="checkbox" checked={!!reply.allow_fallback} onChange={e => setReply(prev => ({ ...prev, allow_fallback: e.target.checked }))} />{t('settingAllowFallback')}</label>
                <label className="checkbox"><input type="checkbox" checked={!!reply.prefer_detected_language} onChange={e => setReply(prev => ({ ...prev, prefer_detected_language: e.target.checked }))} />{t('settingPreferDetectedLanguage')}</label>
              </div>
            </div>
          )}
          {tab === 'ui' && (
            <div className="settings-section">
              <h3>{t('uiBehavior')}</h3>
              <div className="settings-grid">
                <label><span>{t('settingAutoRefresh')}</span><input type="number" value={ui.auto_refresh_seconds || 10} onChange={e => setUi(prev => ({ ...prev, auto_refresh_seconds: Number(e.target.value) || 10 }))} /></label>
                <label className="checkbox"><input type="checkbox" checked={!!ui.show_preview_before_send} onChange={e => setUi(prev => ({ ...prev, show_preview_before_send: e.target.checked }))} />{t('settingPreviewBeforeSend')}</label>
              </div>
              <h3 style={{ marginTop: 18 }}>{t('messageOps') || 'Messages'}</h3>
              <div className="settings-grid">
                <label className="checkbox"><input type="checkbox" checked={!!messageOps.auto_translate} onChange={e => setMessageOps(prev => ({ ...prev, auto_translate: e.target.checked }))} />{t('autoTranslate')}</label>
                <label className="checkbox"><input type="checkbox" checked={!!messageOps.allow_local_hide_delete} onChange={e => setMessageOps(prev => ({ ...prev, allow_local_hide_delete: e.target.checked }))} />{t('settingAllowLocalHide')}</label>
                <label className="checkbox"><input type="checkbox" checked={!!messageOps.allow_bulk_local_hide} onChange={e => setMessageOps(prev => ({ ...prev, allow_bulk_local_hide: e.target.checked }))} />{t('settingAllowBulkHide')}</label>
              </div>
            </div>
          )}
          {tab === 'platforms' && (
            <div className="settings-section">
              <div className="platform-toolbar">
                <div>
                  <h3>平台账号</h3>
                  <p className="subtle">添加多个 WhatsApp / Telegram / Slack / Discord 账号，按平台分组管理。页面只保存账号元数据，不保存敏感凭证。</p>
                </div>
                <div className="platform-add-row">
                  {PLATFORM_OPTIONS.map(option => (
                    <button key={option.platform} className="ghost-btn" onClick={() => addWorkspace(option.platform)}>+ {option.label}</button>
                  ))}
                </div>
              </div>
              {PLATFORM_OPTIONS.map(option => {
                const group = workspaces.filter(item => item.platform === option.platform)
                return (
                  <div className="platform-group" key={option.platform}>
                    <div className="platform-group-title"><span>{option.label}</span><small>{option.category} · {option.method}</small></div>
                    {group.length === 0 ? <div className="subtle platform-empty">暂无账号，点击上方 + {option.label} 添加。</div> : null}
                    {group.map((workspace) => {
                      const idx = workspaces.indexOf(workspace)
                      return (
                        <div className="platform-card" key={workspace.id || idx}>
                          <div className="platform-card-header">
                            <strong>{workspace.label || workspace.id}</strong>
                            <span className={`pill ${workspace.enabled ? 'ok' : 'muted'}`}>{workspace.enabled ? 'Enabled' : 'Disabled'}</span>
                          </div>
                          <div className="settings-grid">
                            <label><span>显示名称</span><input value={workspace.label || ''} onChange={e => updateWorkspace(idx, 'label', e.target.value)} /></label>
                            <label><span>平台</span><select value={workspace.platform || 'whatsapp'} onChange={e => updateWorkspace(idx, 'platform', e.target.value)}>{PLATFORM_OPTIONS.map(item => <option key={item.platform} value={item.platform}>{item.label}</option>)}</select></label>
                            <label><span>Hermes Profile</span><input value={workspace.profile || ''} onChange={e => updateWorkspace(idx, 'profile', e.target.value)} /></label>
                            <label><span>Profile 路径</span><input value={workspace.profile_path || ''} onChange={e => updateWorkspace(idx, 'profile_path', e.target.value)} /></label>
                          </div>
                          <div className="platform-command">
                            <span>登录 / 配对命令</span>
                            <code>{commandFor(workspace)}</code>
                          </div>
                          <div className="platform-actions">
                            <label className="checkbox"><input type="checkbox" checked={!!workspace.enabled} onChange={e => updateWorkspace(idx, 'enabled', e.target.checked)} />启用</label>
                            <label className="checkbox"><input type="checkbox" checked={!!workspace.primary} onChange={e => updateWorkspace(idx, 'primary', e.target.checked)} />主账号</label>
                            <button className="ghost-btn danger" onClick={() => removeWorkspace(idx)}>删除</button>
                          </div>
                        </div>
                      )
                    })}
                  </div>
                )
              })}
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
                    <label><span>{t('settingChannelName')}</span><input value={channel.name} onChange={e => updateField(idx, 'name', e.target.value)} /></label>
                    <label><span>{t('settingPlatform')}</span><input value={channel.platform} onChange={e => updateField(idx, 'platform', e.target.value)} /></label>
                    <label><span>{t('settingTarget')}</span><input value={channel.target} onChange={e => updateField(idx, 'target', e.target.value)} /></label>
                    <label><span>{t('settingKinds')}</span><input value={(channel.kinds || []).join(', ')} onChange={e => updateKinds(idx, e.target.value)} /></label>
                    <label className="checkbox"><input type="checkbox" checked={channel.enabled} onChange={e => updateField(idx, 'enabled', e.target.checked)} />{t('settingEnableChannel')}</label>
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
