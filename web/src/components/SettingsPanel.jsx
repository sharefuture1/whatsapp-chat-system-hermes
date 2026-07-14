import { useEffect, useState } from 'react'
import { useSettings } from '../settings'
import { SUPPORTED_LANGUAGES } from '../i18n'

function makeUserOverrideEntry() {
  return { user_id: '', ai_model: '', custom_system_prompt: '', reply_style: '' }
}

export default function SettingsPanel({
  open,
  initialTab = 'reply',
  selectedConversation = null,
  onOpenAccounts,
  onClose,
  settings,
  channels,
  onSave,
  saving,
  modelDefault = '',
  apiSettings = {},
  onSaveAiSettings,
}) {
  const { t, language, setLanguage, theme, setTheme } = useSettings()
  const [draftChannels, setDraftChannels] = useState(channels)
  const [reply, setReply] = useState(settings?.reply || {})
  const [ui, setUi] = useState(settings?.ui || {})
  const [messageOps, setMessageOps] = useState(settings?.message_ops || { auto_translate: true })

  const [userOverrides, setUserOverrides] = useState(
    Object.entries(settings?.reply?.user_overrides || {}).map(([user_id, value]) => ({
      user_id,
      ...(value || {}),
    })),
  )
  const [password, setPassword] = useState('')
  const [tab, setTab] = useState('reply')

  const [aiBaseUrl, setAiBaseUrl] = useState('')
  const [aiModel, setAiModel] = useState('')
  const [aiApiKey, setAiApiKey] = useState('')
  const [aiSaving, setAiSaving] = useState(false)
  const [aiSaved, setAiSaved] = useState(false)
  const [aiTesting, setAiTesting] = useState(false)
  const [aiTestResult, setAiTestResult] = useState(null) // { ok, message }

  useEffect(() => {
    if (!open) return
    setDraftChannels(channels)
    setReply(settings?.reply || {})
    setUi(settings?.ui || {})
    setMessageOps(settings?.message_ops || { auto_translate: true })
    setUserOverrides(
      Object.entries(settings?.reply?.user_overrides || {}).map(([user_id, value]) => ({
        user_id,
        ...(value || {}),
      })),
    )
    setPassword('')
    setTab(initialTab || 'reply')
  }, [open, channels, settings, initialTab])

  useEffect(() => {
    if (tab !== 'ai') return
    setAiBaseUrl(apiSettings.base_url || '')
    setAiModel(apiSettings.default_model || '')
    setAiApiKey('')
    setAiSaved(false)
  }, [tab, apiSettings])

  useEffect(() => {
    if (!open) return
    const onKey = e => {
      if (e.key === 'Escape') onClose()
    }
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
    setDraftChannels(prev => prev.map((item, i) => (i === index ? { ...item, [key]: value } : item)))
  }

  const updateKinds = (index, value) => {
    setDraftChannels(prev =>
      prev.map((item, i) =>
        i === index ? { ...item, kinds: value.split(',').map(s => s.trim()).filter(Boolean) } : item,
      ),
    )
  }

  const updateUserOverride = (index, key, value) => {
    setUserOverrides(prev => prev.map((item, i) => (i === index ? { ...item, [key]: value } : item)))
  }

  const addUserOverride = () => setUserOverrides(prev => [...prev, makeUserOverrideEntry()])
  const removeUserOverride = index => setUserOverrides(prev => prev.filter((_, i) => i !== index))

  const saveAiSettings = async () => {
    if (!onSaveAiSettings) return
    setAiSaving(true)
    setAiSaved(false)
    try {
      await onSaveAiSettings({
        base_url: aiBaseUrl || null,
        default_model: aiModel || null,
        api_key: aiApiKey || null,
      })
      setAiSaved(true)
      setAiApiKey('')
    } finally {
      setAiSaving(false)
    }
  }

  const testAiConnection = async () => {
    setAiTesting(true)
    setAiTestResult(null)
    try {
      const res = await fetch('/api/v1/ai/test', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'x-session-token': window.__session_token__ || '',
        },
        body: JSON.stringify({
          base_url: aiBaseUrl || undefined,
          default_model: aiModel || undefined,
          api_key: aiApiKey || undefined,
        }),
      })
      const data = await res.json()
      setAiTestResult({ ok: res.ok && data.ok, message: data.message || data.error || (res.ok ? 'OK' : 'Failed') })
    } catch (err) {
      setAiTestResult({ ok: false, message: err.message })
    } finally {
      setAiTesting(false)
    }
  }

  const save = () =>
    onSave(
      {
        channels: draftChannels,
        web_settings: {
          reply: {
            ...reply,
            user_overrides: Object.fromEntries(
              userOverrides
                .filter(item => String(item.user_id || '').trim())
                .map(item => [
                  String(item.user_id).trim(),
                  {
                    ai_model: String(item.ai_model || '').trim(),
                    custom_system_prompt: String(item.custom_system_prompt || '').trim(),
                    reply_style: String(item.reply_style || '').trim(),
                  },
                ]),
            ),
          },
          ui,
          message_ops: messageOps,
        },
        password: password || null,
      },
      () => setPassword(''),
    )

  if (!open) return null

  const tabs = [
    { id: 'reply', label: t('replyPolicy'), hint: t('ai') },
    { id: 'ai', label: t('globalAi'), hint: t('model') },
    { id: 'ui', label: t('uiBehavior'), hint: t('translation') },
    { id: 'accounts', label: t('platformAccounts'), hint: t('whatsappAccounts') },
    { id: 'security', label: t('security'), hint: t('newPassword') },
  ]

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label={t('settings')} onClick={onClose}>
      <div className="modal wx-settings-modal" onClick={e => e.stopPropagation()}>
        <header className="modal-header wx-settings-header">
          <div><h2>{t('settings')}</h2></div>
          <button className="wx-icon-btn" aria-label={t('dismiss')} onClick={onClose}>
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18" /></svg>
          </button>
        </header>
        <div className="wx-settings-layout">
          <div className="wx-settings-nav" role="tablist" aria-label={t('settings')}>
            {tabs.map(item => (
              <button
                key={item.id}
                role="tab"
                aria-selected={tab === item.id}
                className={`tab ${tab === item.id ? 'active' : ''}`}
                onClick={() => setTab(item.id)}
              >
                <span>{item.label}</span>
                <small>{item.hint}</small>
              </button>
            ))}
          </div>
          <div className="modal-body wx-settings-body">
            {tab === 'reply' && (
              <section className="settings-section">
                <h3>{t('replyPolicy')}</h3>
                <div className="settings-grid">
                  <label>
                    <span>{t('settingSmartMax')}</span>
                    <input
                      type="number"
                      value={reply.smart_max_length || 40}
                      onChange={e => setReply(prev => ({ ...prev, smart_max_length: Number(e.target.value) || 40 }))}
                    />
                  </label>
                  <label>
                    <span>{t('settingTranslateMax')}</span>
                    <input
                      type="number"
                      value={reply.translate_max_length || 60}
                      onChange={e => setReply(prev => ({ ...prev, translate_max_length: Number(e.target.value) || 60 }))}
                    />
                  </label>
                  <label className="full-span">
                    <span>{t('settingAiModel')}</span>
                    <input
                      value={reply.ai_model || ''}
                      onChange={e => setReply(prev => ({ ...prev, ai_model: e.target.value }))}
                      placeholder={modelDefault || t('settingAiModelPlaceholder')}
                    />
                    {modelDefault ? (
                      <span className="wx-contact-card-hint">
                        {t('settingAiModelInherit')}：<code>{modelDefault}</code>
                      </span>
                    ) : null}
                  </label>
                  <label>
                    <span>{t('settingPreviewDebounce')}</span>
                    <input
                      type="number"
                      value={reply.preview_debounce_ms || 320}
                      onChange={e => setReply(prev => ({ ...prev, preview_debounce_ms: Number(e.target.value) || 320 }))}
                    />
                  </label>
                  <label className="full-span">
                    <span>{t('settingCustomSystemPrompt')}</span>
                    <textarea
                      rows={4}
                      value={reply.custom_system_prompt || ''}
                      onChange={e => setReply(prev => ({ ...prev, custom_system_prompt: e.target.value }))}
                      placeholder={t('settingCustomSystemPromptHelp')}
                    />
                  </label>
                  <label className="full-span">
                    <span>{t('settingDefaultReplyStyle')}</span>
                    <textarea
                      rows={3}
                      value={reply.default_reply_style || ''}
                      onChange={e => setReply(prev => ({ ...prev, default_reply_style: e.target.value }))}
                      placeholder={t('settingDefaultReplyStyleHelp')}
                    />
                  </label>
                  <label className="checkbox">
                    <input
                      type="checkbox"
                      checked={!!reply.allow_fallback}
                      onChange={e => setReply(prev => ({ ...prev, allow_fallback: e.target.checked }))}
                    />
                    {t('settingAllowFallback')}
                  </label>
                  <label className="checkbox">
                    <input
                      type="checkbox"
                      checked={!!reply.prefer_detected_language}
                      onChange={e => setReply(prev => ({ ...prev, prefer_detected_language: e.target.checked }))}
                    />
                    {t('settingPreferDetectedLanguage')}
                  </label>
                </div>
                <div className="settings-section nested">
                  <div className="platform-toolbar">
                    <div>
                      <h3>{t('perContactReplyConfig')}</h3>
                      <p className="subtle">{t('perContactReplyConfigHelp')}</p>
                    </div>
                    <button className="ghost-btn" type="button" onClick={addUserOverride}>+ {t('addContactRule')}</button>
                  </div>
                  {userOverrides.length === 0 ? (
                    <div className="subtle platform-empty">{t('noContactRules')}</div>
                  ) : null}
                  {userOverrides.map((item, idx) => (
                    <div className="platform-card" key={`${item.user_id || 'new'}-${idx}`}>
                      <div className="settings-grid">
                        <label>
                          <span>{t('contactId')}</span>
                          <input
                            value={item.user_id || ''}
                            onChange={e => updateUserOverride(idx, 'user_id', e.target.value)}
                            placeholder="123456@lid"
                          />
                        </label>
                        <label>
                          <span>{t('settingAiModel')}</span>
                          <input
                            value={item.ai_model || ''}
                            onChange={e => updateUserOverride(idx, 'ai_model', e.target.value)}
                            placeholder={modelDefault || t('settingAiModelInherit')}
                          />
                          {modelDefault ? (
                            <span className="wx-contact-card-hint">
                              {t('settingAiModelInherit')}：<code>{modelDefault}</code>
                            </span>
                          ) : null}
                        </label>
                        <label className="full-span">
                          <span>{t('settingCustomSystemPrompt')}</span>
                          <textarea
                            rows={3}
                            value={item.custom_system_prompt || ''}
                            onChange={e => updateUserOverride(idx, 'custom_system_prompt', e.target.value)}
                            placeholder={t('contactPromptHelp')}
                          />
                        </label>
                        <label className="full-span">
                          <span>{t('settingDefaultReplyStyle')}</span>
                          <textarea
                            rows={2}
                            value={item.reply_style || ''}
                            onChange={e => updateUserOverride(idx, 'reply_style', e.target.value)}
                            placeholder={t('contactStyleHelp')}
                          />
                        </label>
                      </div>
                      <div className="platform-actions">
                        <button className="ghost-btn danger" type="button" onClick={() => removeUserOverride(idx)}>
                          {t('delete')}
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              </section>
            )}

            {tab === 'ai' && (
              <section className="settings-section">
                <h3>{t('globalAi')}</h3>
                <p className="subtle">{t('globalAiSettings')}</p>
                <div className="wx-ai-status-strip">
                  <span className={`pill ${apiSettings.api_key_configured ? 'ok' : 'muted'}`}>
                    {apiSettings.api_key_configured ? t('serviceOnline') : t('notConfigured')}
                  </span>
                  <span>{apiSettings.default_model || t('notConfigured')}</span>
                </div>
                <div className="wx-ai-form">
                  <label className="full-span">
                    <span>{t('apiKey')}</span>
                    <input
                      type="password"
                      value={aiApiKey}
                      onChange={e => { setAiApiKey(e.target.value); setAiTestResult(null) }}
                      placeholder={apiSettings.api_key_configured ? t('apiKeyKeep') : t('apiKeyInput')}
                      autoComplete="new-password"
                    />
                    {apiSettings.api_key_hint ? (
                      <span className="wx-contact-card-hint">
                        {t('apiKeyCurrent')}：{apiSettings.api_key_hint}
                      </span>
                    ) : null}
                  </label>
                  <label className="full-span">
                    <span>{t('settingAiModel')}</span>
                    <input
                      type="text"
                      value={aiModel}
                      onChange={e => { setAiModel(e.target.value); setAiTestResult(null) }}
                      placeholder={apiSettings.default_model || t('settingAiModelPlaceholder')}
                    />
                  </label>
                  <label className="full-span">
                    <span>{t('apiBase')}</span>
                    <input
                      type="url"
                      value={aiBaseUrl}
                      onChange={e => { setAiBaseUrl(e.target.value); setAiTestResult(null) }}
                      placeholder={apiSettings.base_url || 'https://wendingai.future1.us/v1'}
                    />
                  </label>
                </div>
                {aiSaved ? <div className="wx-ai-saved visible">{t('saved')}</div> : <div className="wx-ai-saved" />}
                {aiTestResult && (
                  <div className={`wx-ai-test-result ${aiTestResult.ok ? 'ok' : 'error'}`}>
                    <span className="wx-ai-test-icon">{aiTestResult.ok ? '✓' : '✗'}</span>
                    {aiTestResult.message}
                  </div>
                )}
                <div className="wx-ai-actions">
                  <button className="ghost-btn" type="button" onClick={testAiConnection} disabled={aiTesting}>
                    {aiTesting ? t('testing') + '…' : t('testConnection')}
                  </button>
                  <button className="wx-primary-btn" type="button" onClick={saveAiSettings} disabled={aiSaving}>
                    {aiSaving ? t('saving') : t('save')}
                  </button>
                </div>
              </section>
            )}
            {tab === 'ui' && (
              <section className="settings-section">
                <h3>{t('uiBehavior')}</h3>
                <div className="settings-grid">
                  <label>
                    <span>{t('settingAutoRefresh')}</span>
                    <input
                      type="number"
                      value={ui.auto_refresh_seconds || 10}
                      onChange={e => setUi(prev => ({ ...prev, auto_refresh_seconds: Number(e.target.value) || 10 }))}
                    />
                  </label>
                  <label>
                    <span>{t('language')}</span>
                    <select value={language} onChange={e => setLanguage(e.target.value)}>
                      {SUPPORTED_LANGUAGES.map(l => (
                        <option key={l.code} value={l.code}>{l.label}</option>
                      ))}
                    </select>
                  </label>
                  <label>
                    <span>{t('theme')}</span>
                    <div className="wx-theme-choice" role="group" aria-label={t('theme')}>
                      <button
                        type="button"
                        className={`ghost-btn ${theme === 'light' ? 'active' : ''}`}
                        onClick={() => setTheme('light')}
                      >
                        {t('themeLight')}
                      </button>
                      <button
                        type="button"
                        className={`ghost-btn ${theme === 'dark' ? 'active' : ''}`}
                        onClick={() => setTheme('dark')}
                      >
                        {t('themeDark')}
                      </button>
                    </div>
                  </label>
                  <label className="checkbox">
                    <input
                      type="checkbox"
                      checked={!!ui.show_preview_before_send}
                      onChange={e => setUi(prev => ({ ...prev, show_preview_before_send: e.target.checked }))}
                    />
                    {t('settingPreviewBeforeSend')}
                  </label>
                </div>
                <h3 className="wx-section-subtitle">{t('messageOps')}</h3>
                <div className="settings-grid">
                  <label className="checkbox">
                    <input
                      type="checkbox"
                      checked={!!messageOps.auto_translate}
                      onChange={e => setMessageOps(prev => ({ ...prev, auto_translate: e.target.checked }))}
                    />
                    {t('autoTranslate')}
                  </label>
                  <label className="checkbox">
                    <input
                      type="checkbox"
                      checked={!!messageOps.allow_local_hide_delete}
                      onChange={e => setMessageOps(prev => ({ ...prev, allow_local_hide_delete: e.target.checked }))}
                    />
                    {t('settingAllowLocalHide')}
                  </label>
                  <label className="checkbox">
                    <input
                      type="checkbox"
                      checked={!!messageOps.allow_bulk_local_hide}
                      onChange={e => setMessageOps(prev => ({ ...prev, allow_bulk_local_hide: e.target.checked }))}
                    />
                    {t('settingAllowBulkHide')}
                  </label>
                </div>
              </section>
            )}

            {tab === 'accounts' && (
              <section className="settings-section">
                <div className="platform-toolbar">
                  <div>
                    <h3>{t('platformAccounts')}</h3>
                    <p className="subtle">{t('platformAccountsHelp')}</p>
                  </div>
                  <button className="wx-primary-btn" type="button" onClick={onOpenAccounts}>
                    {t('manageAccounts')}
                  </button>
                </div>
                <div className="wx-settings-account-entry">
                  <strong>{t('whatsappAccounts')}</strong>
                  <span>{t('accountCenterHint')}</span>
                  <button className="ghost-btn" type="button" onClick={onOpenAccounts}>
                    {t('openAccountCenter')}
                  </button>
                </div>
                <details className="wx-advanced-disclosure">
                  <summary>{t('advanced')}</summary>
                  <div className="channels-grid">
                    {draftChannels.map((channel, idx) => (
                      <div className="channel-card" key={channel.id}>
                        <div className="channel-card-header">
                          <strong>{channel.name}</strong>
                          <span className={`pill ${channel.enabled ? 'ok' : 'muted'}`}>
                            {channel.enabled ? t('enabled') : t('disabled')}
                          </span>
                        </div>
                        <label>
                          <span>{t('settingChannelName')}</span>
                          <input value={channel.name} onChange={e => updateField(idx, 'name', e.target.value)} />
                        </label>
                        <label>
                          <span>{t('settingPlatform')}</span>
                          <input value={channel.platform} onChange={e => updateField(idx, 'platform', e.target.value)} />
                        </label>
                        <label>
                          <span>{t('settingTarget')}</span>
                          <input value={channel.target} onChange={e => updateField(idx, 'target', e.target.value)} />
                        </label>
                        <label>
                          <span>{t('settingKinds')}</span>
                          <input
                            value={(channel.kinds || []).join(', ')}
                            onChange={e => updateKinds(idx, e.target.value)}
                          />
                        </label>
                        <label className="checkbox">
                          <input
                            type="checkbox"
                            checked={channel.enabled}
                            onChange={e => updateField(idx, 'enabled', e.target.checked)}
                          />
                          {t('settingEnableChannel')}
                        </label>
                      </div>
                    ))}
                  </div>
                </details>
              </section>
            )}

            {tab === 'security' && (
              <section className="settings-section">
                <h3>{t('security')}</h3>
                <div className="settings-grid">
                  <label>
                    <span>{t('newPassword')}</span>
                    <input
                      type="password"
                      value={password}
                      onChange={e => setPassword(e.target.value)}
                      autoComplete="new-password"
                    />
                  </label>
                </div>
                <p className="subtle">{t('newPasswordHelp')}</p>
              </section>
            )}
          </div>
        </div>
        <footer className="modal-footer wx-settings-footer">
          <button className="ghost-btn" type="button" onClick={onClose}>{t('back')}</button>
          <button className="wx-primary-btn" type="button" onClick={save} disabled={saving}>
            {saving ? t('saving') : t('save')}
          </button>
        </footer>
      </div>
    </div>
  )
}
