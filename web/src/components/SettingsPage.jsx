import { useEffect, useState } from 'react'
import { useSettings } from '../settings'

const ShieldIcon = () => (
  <svg viewBox="0 0 24 24" aria-hidden="true">
    <path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z" />
    <path d="M9 12l2 2 4-4" />
  </svg>
)
const SparkleIcon = () => (
  <svg viewBox="0 0 24 24" aria-hidden="true">
    <path d="M12 3l1.8 4.6L18 9l-4.2 1.4L12 15l-1.8-4.6L6 9l4.2-1.4z" />
    <path d="M19 14l.7 1.7L21 16l-1.3.3L19 18l-.7-1.7L17 16l1.3-.3z" />
  </svg>
)
const ChatIcon = () => (
  <svg viewBox="0 0 24 24" aria-hidden="true">
    <path d="M4 5h16a1 1 0 0 1 1 1v11a1 1 0 0 1-1 1h-9l-4 3v-3H4a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1z" />
  </svg>
)
const GeneralIcon = () => (
  <svg viewBox="0 0 24 24" aria-hidden="true">
    <circle cx="12" cy="12" r="3" />
    <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 0 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 0 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 0 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 0 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 0 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 0 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 0 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 0 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z" />
  </svg>
)
const InfoIcon = () => (
  <svg viewBox="0 0 24 24" aria-hidden="true">
    <circle cx="12" cy="12" r="9" />
    <path d="M12 8h.01M11 12h1v4h1" />
  </svg>
)
const ChevronRight = () => (
  <svg viewBox="0 0 24 24" aria-hidden="true" className="wx-cell-arrow">
    <path d="M9 6l6 6-6 6" />
  </svg>
)

/**
 * 微信式全屏设置主页（替代 SettingsPanel 模态）。
 * 由 App.jsx 路由控制打开：setSettingsView('main') / 'security' / 'ai' / 'chat' / 'about' / 'general'。
 */
export default function SettingsPage({
  view = 'main', // 'main' | 'security' | 'ai' | 'chat' | 'general' | 'about'
  onNavigate,
  onBack,
  currentUser = { username: '', role: 'admin' },
  aiConfigured = false,
  aiModel = '',
  autoTranslate = false,
  healthOk = false,
  accountSummary = { total: 0, online: 0 },
  theme = 'light',
  language = 'zh',
  setTheme,
  setLanguage,
  languages = [],
  pluginCount = 0,
  webSettings = {},
  channels = [],
  saving = false,
  onSaveSettings,
  onSaveAiSettings,
  apiSettings = {},
  onOpenAccounts,
  onOpenUserMgm,
}) {
  const { t } = useSettings()
  const isAdmin = currentUser?.role === 'admin'

  if (view === 'main') {
    return (
      <section className="wx-page wx-settings-page">
        <header className="wx-page-header wx-settings-page-header">
          <button
            type="button"
            className="wx-icon-btn wx-page-header-back"
            onClick={onBack}
            aria-label={t('back')}
            title={t('back')}
          >
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path d="M15 6l-6 6 6 6" />
            </svg>
          </button>
          <h2>{t('settings')}</h2>
        </header>

        <div className="wx-cell-group">
          <div className="wx-section-list wx-card-list">
            <button
              type="button"
              className="wx-setting-row link"
              onClick={() => onNavigate('security')}
            >
              <span className="wx-setting-row-icon"><ShieldIcon /></span>
              <span>
                <strong>{t('settingsSecurity')}</strong>
                <small>{t('settingsSecuritySub')}</small>
              </span>
              <ChevronRight />
            </button>
            <button
              type="button"
              className="wx-setting-row link"
              onClick={() => onNavigate('ai')}
            >
              <span className="wx-setting-row-icon"><SparkleIcon /></span>
              <span>
                <strong>{t('settingsAi')}</strong>
                <small>
                  {aiConfigured
                    ? `${t('enabled')} · ${aiModel || 'AI'}`
                    : t('notConfigured')}
                </small>
              </span>
              <span className={`pill ${aiConfigured ? 'ok' : 'muted'}`}>
                {aiConfigured ? t('on') : t('off')}
              </span>
              <ChevronRight />
            </button>
          </div>
        </div>

        <div className="wx-cell-group">
          <div className="wx-section-list wx-card-list">
            <button
              type="button"
              className="wx-setting-row link"
              onClick={() => onNavigate('chat')}
            >
              <span className="wx-setting-row-icon"><ChatIcon /></span>
              <span>
                <strong>{t('settingsChat')}</strong>
                <small>{t('settingsChatSub')}</small>
              </span>
              <ChevronRight />
            </button>
            <button
              type="button"
              className="wx-setting-row link"
              onClick={() => onNavigate('general')}
            >
              <span className="wx-setting-row-icon"><GeneralIcon /></span>
              <span>
                <strong>{t('settingsGeneral')}</strong>
                <small>
                  {theme === 'dark' ? t('themeDark') : t('themeLight')} · {language}
                </small>
              </span>
              <ChevronRight />
            </button>
          </div>
        </div>

        <div className="wx-cell-group">
          <div className="wx-section-list wx-card-list">
            <button
              type="button"
              className="wx-setting-row link"
              onClick={() => onNavigate('about')}
            >
              <span className="wx-setting-row-icon"><InfoIcon /></span>
              <span>
                <strong>{t('settingsAbout')}</strong>
                <small>{t('settingsAboutSub')}</small>
              </span>
              <ChevronRight />
            </button>
          </div>
        </div>

        <div className="wx-cell-group">
          <div className="wx-section-list wx-card-list">
            <div className="wx-setting-row">
              <span>{t('operator')}</span>
              <span className="wx-setting-value">
                {currentUser.username || 'admin'} · {isAdmin ? t('roleAdmin') : t('roleOperator')}
              </span>
            </div>
            <div className="wx-setting-row">
              <span>{t('whatsappAccounts')}</span>
              <span className="wx-setting-value">
                {accountSummary.online}/{accountSummary.total} {t('online')}
              </span>
            </div>
            <div className="wx-setting-row">
              <span>{t('pluginCenter')}</span>
              <span className="wx-setting-value">{pluginCount}</span>
            </div>
            <div className="wx-setting-row">
              <span>{t('serviceStatus')}</span>
              <span className={`pill ${healthOk ? 'ok' : 'muted'}`}>
                {healthOk ? t('serviceOnline') : t('serviceOffline')}
              </span>
            </div>
          </div>
        </div>
      </section>
    )
  }

  // 子页面通用框架
  const titles = {
    security: t('settingsSecurity'),
    ai: t('settingsAi'),
    chat: t('settingsChat'),
    general: t('settingsGeneral'),
    about: t('settingsAbout'),
  }
  return (
    <section className="wx-page wx-settings-page wx-settings-subpage">
      <header className="wx-page-header wx-settings-page-header">
        <button
          type="button"
          className="wx-icon-btn wx-page-header-back"
          onClick={() => onNavigate('main')}
          aria-label={t('back')}
          title={t('back')}
        >
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M15 6l-6 6 6 6" />
          </svg>
        </button>
        <h2>{titles[view] || t('settings')}</h2>
      </header>
      <div className="wx-settings-subpage-body">
        {view === 'ai' ? (
          <AiSubPage
            isAdmin={isAdmin}
            apiSettings={apiSettings}
            onSaveAiSettings={onSaveAiSettings}
          />
        ) : null}
        {view === 'chat' ? (
          <ChatSubPage
            webSettings={webSettings}
            channels={channels}
            saving={saving}
            onSaveSettings={onSaveSettings}
          />
        ) : null}
        {view === 'general' ? (
          <GeneralSubPage
            theme={theme}
            language={language}
            setTheme={setTheme}
            setLanguage={setLanguage}
            languages={languages}
          />
        ) : null}
        {view === 'security' ? (
          <SecuritySubPage
            isAdmin={isAdmin}
            webSettings={webSettings}
            channels={channels}
            saving={saving}
            onSaveSettings={onSaveSettings}
            onOpenAccounts={onOpenAccounts}
            onOpenUserMgm={onOpenUserMgm}
          />
        ) : null}
        {view === 'about' ? <AboutSubPage /> : null}
      </div>
    </section>
  )
}

/* 子页：占位实现，由 App.jsx 在 onNavigate 阶段可继续保留旧 SettingsPanel 的具体 form 渲染。
   本轮先保证架构完整：路由可达、视觉到位、键盘可达。
   子页内部从 props/onNavigate 衍生；以下组件在后续 PR 中接真实数据。 */

function AiSubPage({ isAdmin, apiSettings = {}, onSaveAiSettings }) {
  const { t } = useSettings()
  const [baseUrl, setBaseUrl] = useState(apiSettings.base_url || '')
  const [model, setModel] = useState(apiSettings.default_model || '')
  const [apiKey, setApiKey] = useState('')
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    setBaseUrl(apiSettings.base_url || '')
    setModel(apiSettings.default_model || '')
    setApiKey('')
    setSaved(false)
  }, [apiSettings])

  const save = async () => {
    if (!isAdmin || !onSaveAiSettings) return
    setSaving(true)
    setSaved(false)
    try {
      await onSaveAiSettings({ base_url: baseUrl || null, default_model: model || null, api_key: apiKey || null })
      setApiKey('')
      setSaved(true)
    } finally {
      setSaving(false)
    }
  }

  return (
    <>
      <div className="wx-cell-group">
        <div className="wx-cell-group-title">{t('globalAi')}</div>
        <div className="wx-section-list wx-card-list">
          {isAdmin ? (
            <>
              <label className="wx-setting-row wx-setting-row-form multi">
                <span>
                  <strong>{t('baseUrl') || 'Base URL'}</strong>
                  <small>{t('settingsAiSub')}</small>
                </span>
                <input value={baseUrl} onChange={e => setBaseUrl(e.target.value)} placeholder="https://wendingai.future1.us/v1" />
              </label>
              <label className="wx-setting-row wx-setting-row-form multi">
                <span>
                  <strong>{t('model')}</strong>
                  <small>{t('settingAiModelInherit') || 'Model'}</small>
                </span>
                <input value={model} onChange={e => setModel(e.target.value)} placeholder="gpt-5.3-codex-spark" />
              </label>
              <label className="wx-setting-row wx-setting-row-form multi">
                <span>
                  <strong>{t('apiKey') || 'API Key'}</strong>
                  <small>{t('apiKeyKeep') || 'Leave blank to keep current key'}</small>
                </span>
                <input type="password" value={apiKey} onChange={e => setApiKey(e.target.value)} placeholder={t('apiKeyInput') || 'Paste new API key'} />
              </label>
              <div className="wx-setting-row">
                <span>{t('configured')}</span>
                <span className="wx-setting-value">{apiSettings.api_key_configured ? t('yes') || 'Yes' : t('no') || 'No'}</span>
              </div>
              <div className="wx-setting-row">
                <button type="button" className="ghost-btn" onClick={save} disabled={saving}>{saving ? (t('saving') || 'Saving...') : (t('save') || 'Save')}</button>
                {saved ? <span className="pill ok">{t('saved') || 'Saved'}</span> : null}
              </div>
            </>
          ) : (
            <div className="wx-empty-tip">{t('settingsAiOperatorHint')}</div>
          )}
        </div>
      </div>
    </>
  )
}

function ChatSubPage({ webSettings = {}, channels = [], saving = false, onSaveSettings }) {
  const { t } = useSettings()
  const [autoTranslate, setAutoTranslate] = useState(!!webSettings?.message_ops?.auto_translate)
  const [previewDebounce, setPreviewDebounce] = useState(Number(webSettings?.reply?.preview_debounce_ms || 320))
  const [smartMax, setSmartMax] = useState(Number(webSettings?.reply?.smart_max_length || 40))
  const [translateMax, setTranslateMax] = useState(Number(webSettings?.reply?.translate_max_length || 60))

  useEffect(() => {
    setAutoTranslate(!!webSettings?.message_ops?.auto_translate)
    setPreviewDebounce(Number(webSettings?.reply?.preview_debounce_ms || 320))
    setSmartMax(Number(webSettings?.reply?.smart_max_length || 40))
    setTranslateMax(Number(webSettings?.reply?.translate_max_length || 60))
  }, [webSettings])

  const save = () => onSaveSettings?.({
    channels,
    web_settings: {
      ...webSettings,
      reply: {
        ...(webSettings.reply || {}),
        preview_debounce_ms: previewDebounce,
        smart_max_length: smartMax,
        translate_max_length: translateMax,
      },
      message_ops: {
        ...(webSettings.message_ops || {}),
        auto_translate: autoTranslate,
      },
    },
  })

  return (
    <div className="wx-cell-group">
      <div className="wx-cell-group-title">{t('chat')}</div>
      <div className="wx-section-list wx-card-list">
        <label className="wx-setting-row wx-setting-row-form">
          <span>{t('autoTranslate')}</span>
          <input type="checkbox" checked={autoTranslate} onChange={e => setAutoTranslate(e.target.checked)} />
        </label>
        <label className="wx-setting-row wx-setting-row-form">
          <span>{t('settingPreviewDebounce')}</span>
          <input type="number" value={previewDebounce} onChange={e => setPreviewDebounce(Number(e.target.value) || 320)} />
        </label>
        <label className="wx-setting-row wx-setting-row-form">
          <span>{t('settingSmartMax')}</span>
          <input type="number" value={smartMax} onChange={e => setSmartMax(Number(e.target.value) || 40)} />
        </label>
        <label className="wx-setting-row wx-setting-row-form">
          <span>{t('settingTranslateMax')}</span>
          <input type="number" value={translateMax} onChange={e => setTranslateMax(Number(e.target.value) || 60)} />
        </label>
        <div className="wx-setting-row">
          <button type="button" className="ghost-btn" onClick={save} disabled={saving}>{saving ? (t('saving') || 'Saving...') : (t('save') || 'Save')}</button>
        </div>
      </div>
    </div>
  )
}

function GeneralSubPage({ theme, language, setTheme, setLanguage, languages }) {
  const { t } = useSettings()
  return (
    <>
      <div className="wx-cell-group">
        <div className="wx-cell-group-title">{t('appearance')}</div>
        <div className="wx-section-list wx-card-list">
          <label className="wx-setting-row wx-setting-row-form">
            <span>{t('theme')}</span>
            <select value={theme} onChange={e => setTheme?.(e.target.value)}>
              <option value="light">{t('themeLight')}</option>
              <option value="dark">{t('themeDark')}</option>
            </select>
          </label>
        </div>
      </div>
      <div className="wx-cell-group">
        <div className="wx-cell-group-title">{t('language')}</div>
        <div className="wx-section-list wx-card-list">
          <label className="wx-setting-row wx-setting-row-form">
            <span>{t('language')}</span>
            <select value={language} onChange={e => setLanguage?.(e.target.value)}>
              {(languages || []).map(l => (
                <option key={l.code} value={l.code}>{l.label}</option>
              ))}
            </select>
          </label>
        </div>
      </div>
    </>
  )
}

function SecuritySubPage({ isAdmin, onOpenAccounts, onOpenUserMgm }) {
  const { t } = useSettings()
  return (
    <div className="wx-cell-group">
      <div className="wx-cell-group-title">{t('security')}</div>
      <div className="wx-section-list wx-card-list">
        <div className="wx-setting-row">
          <span>{t('changePassword')}</span>
          <span className="wx-setting-value">{t('settingsSecuritySub')}</span>
        </div>
        <button type="button" className="wx-setting-row link" onClick={() => onOpenAccounts?.()}>
          <span>{t('whatsappAccounts')}</span>
          <span className="wx-setting-value">›</span>
        </button>
        {isAdmin ? (
          <button type="button" className="wx-setting-row link" onClick={() => onOpenUserMgm?.()}>
            <span>{t('userManagement')}</span>
            <span className="wx-setting-value">›</span>
          </button>
        ) : null}
      </div>
    </div>
  )
}

function AboutSubPage() {
  const { t } = useSettings()
  return (
    <div className="wx-cell-group">
      <div className="wx-section-list wx-card-list">
        <div className="wx-setting-row">
          <span>{t('appName')}</span>
          <span className="wx-setting-value">WhatsApp Chat System</span>
        </div>
        <div className="wx-setting-row">
          <span>{t('version')}</span>
          <span className="wx-setting-value wx-mono">v1.0.0</span>
        </div>
        <div className="wx-setting-row">
          <span>{t('serviceStatus')}</span>
          <span className="wx-setting-value">{t('serviceOnline')}</span>
        </div>
      </div>
    </div>
  )
}
