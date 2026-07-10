import { useEffect, useState } from 'react'
import { useSettings } from '../settings'
import ToolsPanel from './ToolsPanel'

const PLATFORM_OPTIONS = [
  { platform: 'whatsapp', label: 'WhatsApp', categoryKey: 'platformChat', methodKey: 'platformQr', command: 'hermes -p <profile> whatsapp' },
  { platform: 'telegram', label: 'Telegram', categoryKey: 'platformChat', methodKey: 'platformManual', command: 'hermes -p <profile> telegram' },
  { platform: 'slack', label: 'Slack', categoryKey: 'platformTeam', methodKey: 'platformManual', command: 'hermes -p <profile> slack' },
  { platform: 'discord', label: 'Discord', categoryKey: 'platformCommunity', methodKey: 'platformManual', command: 'hermes -p <profile> discord' },
]

function makeWorkspace(platform = 'whatsapp') {
  const id = `${platform}-${Date.now()}`
  return { id, label: `${platform} account`, platform, profile: id, profile_path: `/root/.hermes/profiles/${id}`, enabled: true, primary: false }
}

function makeUserOverrideEntry() {
  return { user_id: '', ai_model: '', custom_system_prompt: '', reply_style: '' }
}

function commandFor(workspace) {
  const option = PLATFORM_OPTIONS.find(item => item.platform === workspace.platform) || PLATFORM_OPTIONS[0]
  return option.command.replace('<profile>', workspace.profile || workspace.id || workspace.platform)
}

export default function SettingsPanel({ open, initialTab = 'reply', selectedConversation = null, onClose, settings, channels, onSave, saving, modelDefault = '' }) {
  const { t } = useSettings()
  const [draftChannels, setDraftChannels] = useState(channels)
  const [reply, setReply] = useState(settings?.reply || {})
  const [ui, setUi] = useState(settings?.ui || {})
  const [messageOps, setMessageOps] = useState(settings?.message_ops || { auto_translate: true })
  const [workspaces, setWorkspaces] = useState(settings?.workspaces || [])
  const [userOverrides, setUserOverrides] = useState(Object.entries(settings?.reply?.user_overrides || {}).map(([user_id, value]) => ({ user_id, ...(value || {}) })))
  const [password, setPassword] = useState('')
  const [tab, setTab] = useState('reply')

  useEffect(() => {
    if (!open) return
    setDraftChannels(channels)
    setReply(settings?.reply || {})
    setUi(settings?.ui || {})
    setMessageOps(settings?.message_ops || { auto_translate: true })
    setWorkspaces(settings?.workspaces || [])
    setUserOverrides(Object.entries(settings?.reply?.user_overrides || {}).map(([user_id, value]) => ({ user_id, ...(value || {}) })))
    setPassword('')
    setTab(initialTab || 'reply')
  }, [open, channels, settings, initialTab])

  useEffect(() => {
    if (!open) return
    const onKey = e => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onClose])

  useEffect(() => {
    if (!open || !selectedConversation?.user_id || (initialTab || 'reply') !== 'reply') return
    setUserOverrides(prev => {
      if (prev.some(item => String(item.user_id || '').trim() === String(selectedConversation.user_id).trim())) return prev
      return [{ user_id: String(selectedConversation.user_id), ai_model: '', custom_system_prompt: '', reply_style: '' }, ...prev]
    })
  }, [open, selectedConversation, initialTab])

  const updateField = (index, key, value) => {
    setDraftChannels(prev => prev.map((item, i) => i === index ? { ...item, [key]: value } : item))
  }

  const updateKinds = (index, value) => {
    setDraftChannels(prev => prev.map((item, i) => i === index ? { ...item, kinds: value.split(',').map(s => s.trim()).filter(Boolean) } : item))
  }

  const updateWorkspace = (index, key, value) => {
    setWorkspaces(prev => prev.map((item, i) => i === index ? { ...item, [key]: value } : item))
  }

  const updateUserOverride = (index, key, value) => {
    setUserOverrides(prev => prev.map((item, i) => i === index ? { ...item, [key]: value } : item))
  }

  const addUserOverride = () => {
    setUserOverrides(prev => [...prev, makeUserOverrideEntry()])
  }

  const removeUserOverride = (index) => {
    setUserOverrides(prev => prev.filter((_, i) => i !== index))
  }

  const addWorkspace = (platform = 'whatsapp') => {
    setWorkspaces(prev => [...prev, makeWorkspace(platform)])
  }

  const removeWorkspace = (index) => {
    setWorkspaces(prev => prev.filter((_, i) => i !== index))
  }

  const save = () => onSave({
    channels: draftChannels,
    web_settings: {
      reply: {
        ...reply,
        user_overrides: Object.fromEntries(
          userOverrides
            .filter(item => String(item.user_id || '').trim())
            .map(item => [String(item.user_id).trim(), {
              ai_model: String(item.ai_model || '').trim(),
              custom_system_prompt: String(item.custom_system_prompt || '').trim(),
              reply_style: String(item.reply_style || '').trim(),
            }])
        ),
      },
      ui,
      message_ops: messageOps,
      workspaces,
    },
    password: password || null,
  }, () => setPassword(''))

  if (!open) return null

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label={t('settings')} onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <div className="modal-header wx-settings-header">
          <div>
            <div className="wx-settings-eyebrow">WeChat Style Settings</div>
            <h2>{t('settings')}</h2>
          </div>
          <button className="wx-icon-btn" aria-label={t('dismiss')} onClick={onClose}>
            <svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18"/></svg>
          </button>
        </div>
        <div className="wx-settings-layout">
          <div className="modal-tabs wx-settings-nav" role="tablist">
            <button role="tab" aria-selected={tab==='reply'} className={`tab ${tab==='reply' ? 'active' : ''}`} onClick={() => setTab('reply')}>
              <span>{t('replyPolicy')}</span>
              <small>AI / Prompt / 风格</small>
            </button>
            <button role="tab" aria-selected={tab==='ui'} className={`tab ${tab==='ui' ? 'active' : ''}`} onClick={() => setTab('ui')}>
              <span>{t('uiBehavior')}</span>
              <small>界面 / 自动翻译</small>
            </button>
            <button role="tab" aria-selected={tab==='channels'} className={`tab ${tab==='channels' ? 'active' : ''}`} onClick={() => setTab('channels')}>
              <span>{t('channels')}</span>
              <small>投递目标</small>
            </button>
            <button role="tab" aria-selected={tab==='platforms'} className={`tab ${tab==='platforms' ? 'active' : ''}`} onClick={() => setTab('platforms')}>
              <span>{t('platformAccounts')}</span>
              <small>账号 / Profile</small>
            </button>
            <button role="tab" aria-selected={tab==='tools'} className={`tab ${tab==='tools' ? 'active' : ''}`} onClick={() => setTab('tools')}>
              <span>{t('tools') || '工具'}</span>
              <small>定时 / 群发 / 插件</small>
            </button>
            <button role="tab" aria-selected={tab==='security'} className={`tab ${tab==='security' ? 'active' : ''}`} onClick={() => setTab('security')}>
              <span>{t('security')}</span>
              <small>密码</small>
            </button>
          </div>
          <div className="modal-body wx-settings-body">
          {tab === 'reply' && (
            <div className="settings-section">
              <h3>{t('replyPolicy')}</h3>
              <div className="settings-grid">
                <label><span>{t('settingSmartMax')}</span><input type="number" value={reply.smart_max_length || 40} onChange={e => setReply(prev => ({ ...prev, smart_max_length: Number(e.target.value) || 40 }))} /></label>
                <label><span>{t('settingTranslateMax')}</span><input type="number" value={reply.translate_max_length || 60} onChange={e => setReply(prev => ({ ...prev, translate_max_length: Number(e.target.value) || 60 }))} /></label>
                <label><span>{t('settingAiModel') || 'AI 模型'}</span><input value={reply.ai_model || ''} onChange={e => setReply(prev => ({ ...prev, ai_model: e.target.value }))} placeholder={modelDefault || t('settingAiModelPlaceholder') || '服务端默认模型'} />{modelDefault ? <span className="wx-contact-card-hint">{t('settingAiModelInherit') || '留空则继承服务端默认'}：<code>{modelDefault}</code></span> : null}</label>
                <label><span>{t('settingPreviewDebounce')}</span><input type="number" value={reply.preview_debounce_ms || 320} onChange={e => setReply(prev => ({ ...prev, preview_debounce_ms: Number(e.target.value) || 320 }))} /></label>
                <label className="full-span"><span>{t('settingCustomSystemPrompt') || '默认系统提示词'}</span><textarea rows="4" value={reply.custom_system_prompt || ''} onChange={e => setReply(prev => ({ ...prev, custom_system_prompt: e.target.value }))} placeholder={t('settingCustomSystemPromptHelp') || '全局 AI 提示词，会追加到系统指令中'} /></label>
                <label className="full-span"><span>{t('settingDefaultReplyStyle') || '默认回复风格'}</span><textarea rows="3" value={reply.default_reply_style || ''} onChange={e => setReply(prev => ({ ...prev, default_reply_style: e.target.value }))} placeholder={t('settingDefaultReplyStyleHelp') || '例如：像熟人聊天、短句、温柔一点、少模板感'} /></label>
                <label className="checkbox"><input type="checkbox" checked={!!reply.allow_fallback} onChange={e => setReply(prev => ({ ...prev, allow_fallback: e.target.checked }))} />{t('settingAllowFallback')}</label>
                <label className="checkbox"><input type="checkbox" checked={!!reply.prefer_detected_language} onChange={e => setReply(prev => ({ ...prev, prefer_detected_language: e.target.checked }))} />{t('settingPreferDetectedLanguage')}</label>
              </div>
              <div className="settings-section nested">
                <div className="platform-toolbar">
                  <div>
                    <h3>{t('perContactReplyConfig') || '按联系人自定义 AI'}</h3>
                    <p className="subtle">{t('perContactReplyConfigHelp') || '可为单个聊天对象指定模型、提示词和回复风格，优先级高于全局默认设置。'}</p>
                  </div>
                  <button className="ghost-btn" onClick={addUserOverride}>+ {t('addContactRule') || '添加联系人规则'}</button>
                </div>
                {userOverrides.length === 0 ? <div className="subtle platform-empty">{t('noContactRules') || '暂无联系人规则'}</div> : null}
                {userOverrides.map((item, idx) => (
                  <div className="platform-card" key={`${item.user_id || 'new'}-${idx}`}>
                    <div className="settings-grid">
                      <label><span>{t('contactId') || '联系人ID'}</span><input value={item.user_id || ''} onChange={e => updateUserOverride(idx, 'user_id', e.target.value)} placeholder="如 123456@lid" /></label>
                      <label><span>{t('settingAiModel') || 'AI 模型'}</span><input value={item.ai_model || ''} onChange={e => updateUserOverride(idx, 'ai_model', e.target.value)} placeholder={modelDefault || t('settingAiModelInherit') || '留空则继承全局'} />{modelDefault ? <span className="wx-contact-card-hint">{t('settingAiModelInherit') || '留空则继承全局'}：<code>{modelDefault}</code></span> : null}</label>
                      <label className="full-span"><span>{t('settingCustomSystemPrompt') || '系统提示词'}</span><textarea rows="3" value={item.custom_system_prompt || ''} onChange={e => updateUserOverride(idx, 'custom_system_prompt', e.target.value)} placeholder={t('contactPromptHelp') || '例如：这个用户比较敏感，回复时要更温柔、更口语化'} /></label>
                      <label className="full-span"><span>{t('settingDefaultReplyStyle') || '回复风格'}</span><textarea rows="2" value={item.reply_style || ''} onChange={e => updateUserOverride(idx, 'reply_style', e.target.value)} placeholder={t('contactStyleHelp') || '例如：像熟悉朋友聊天，短句，先共情再回答'} /></label>
                    </div>
                    <div className="platform-actions">
                      <button className="ghost-btn danger" onClick={() => removeUserOverride(idx)}>{t('delete')}</button>
                    </div>
                  </div>
                ))}
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
                  <h3>{t('platformAccounts')}</h3>
                  <p className="subtle">{t('platformAccountsHelp')}</p>
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
                    <div className="platform-group-title"><span>{option.label}</span><small>{t(option.categoryKey)} · {t(option.methodKey)}</small></div>
                    {group.length === 0 ? <div className="subtle platform-empty">{t('noPlatformAccounts')}</div> : null}
                    {group.map((workspace) => {
                      const idx = workspaces.indexOf(workspace)
                      return (
                        <div className="platform-card" key={workspace.id || idx}>
                          <div className="platform-card-header">
                            <strong>{workspace.label || workspace.id}</strong>
                            <span className={`pill ${workspace.enabled ? 'ok' : 'muted'}`}>{workspace.enabled ? t('enabled') : t('disabled')}</span>
                          </div>
                          <div className="settings-grid">
                            <label><span>{t('displayName')}</span><input value={workspace.label || ''} onChange={e => updateWorkspace(idx, 'label', e.target.value)} /></label>
                            <label><span>{t('settingPlatform')}</span><select value={workspace.platform || 'whatsapp'} onChange={e => updateWorkspace(idx, 'platform', e.target.value)}>{PLATFORM_OPTIONS.map(item => <option key={item.platform} value={item.platform}>{item.label}</option>)}</select></label>
                            <label><span>{t('hermesProfile')}</span><input value={workspace.profile || ''} onChange={e => updateWorkspace(idx, 'profile', e.target.value)} /></label>
                            <label><span>{t('profilePath')}</span><input value={workspace.profile_path || ''} onChange={e => updateWorkspace(idx, 'profile_path', e.target.value)} /></label>
                          </div>
                          <div className="platform-command">
                            <span>{t('connectCommand')}</span>
                            <code>{commandFor(workspace)}</code>
                          </div>
                          <div className="platform-actions">
                            <label className="checkbox"><input type="checkbox" checked={!!workspace.enabled} onChange={e => updateWorkspace(idx, 'enabled', e.target.checked)} />{t('enable')}</label>
                            <label className="checkbox"><input type="checkbox" checked={!!workspace.primary} onChange={e => updateWorkspace(idx, 'primary', e.target.checked)} />{t('primaryAccount')}</label>
                            <button className="ghost-btn danger" onClick={() => removeWorkspace(idx)}>{t('delete')}</button>
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
                      <span className={`pill ${channel.enabled ? 'ok' : 'muted'}`}>{channel.enabled ? t('enabled') : t('disabled')}</span>
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
          {tab === 'tools' && <ToolsPanel />}
        </div>
        </div>
        <div className="modal-footer">
          <button className="ghost-btn" onClick={onClose}>{t('back')}</button>
          <button className="wx-primary-btn" onClick={save} disabled={saving}>{saving ? t('saving') : t('save')}</button>
        </div>
      </div>
    </div>
  )
}
