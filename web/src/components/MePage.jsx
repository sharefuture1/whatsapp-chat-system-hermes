import { useSettings } from '../settings'

const AccountsIcon = () => (
  <svg viewBox="0 0 24 24" aria-hidden="true">
    <path d="M7 3h10a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2Z" />
    <path d="M10 18h4" />
  </svg>
)
const OperatorIcon = () => (
  <svg viewBox="0 0 24 24" aria-hidden="true">
    <circle cx="12" cy="8" r="4" />
    <path d="M4 21c0-4 3.6-7 8-7s8 3 8 7" />
  </svg>
)
const PluginsIcon = () => (
  <svg viewBox="0 0 24 24" aria-hidden="true">
    <path d="M9 4h6v4h4v6h-4v4h-6v-4H5V8h4z" />
    <circle cx="12" cy="11" r="1.4" />
  </svg>
)
const AiIcon = () => (
  <svg viewBox="0 0 24 24" aria-hidden="true">
    <path d="M12 3a7 7 0 0 1 7 7v4a3 3 0 0 1-3 3h-1l-3 3-3-3H8a3 3 0 0 1-3-3v-4a7 7 0 0 1 7-7Z" />
    <path d="M9 10h.01M15 10h.01M9.5 14h5" />
  </svg>
)

export default function MePage({
  health,
  onOpenSettings,
  onOpenGlobalAi,
  onOpenAccounts,
  onOpenPlugins,
  onLogout,
  autoTranslate,
  accountSummary,
  aiSummary,
}) {
  const { t, language, setLanguage, languages, theme, setTheme } = useSettings()
  return (
    <section className="wx-page wx-me-page">
      <header className="wx-me-hero">
        <div className="wx-avatar lg wx-operator-avatar" style={{ background: '#07c160' }}>
          <OperatorIcon />
        </div>
        <div className="wx-me-hero-meta">
          <div className="wx-me-name">{t('operator')}</div>
          <div className="wx-me-sub">{t('operatorRole')}</div>
          <div className="wx-me-status-row">
            <span className={`pill ${health ? 'ok' : 'muted'}`}>
              {health ? t('serviceOnline') : t('serviceOffline')}
            </span>
            <span className="pill muted">{t('autoTranslate')}</span>
          </div>
        </div>
      </header>

      <div className="wx-cell-group">
        <div className="wx-cell-group-title">{t('accountAndConnection')}</div>
        <div className="wx-section-list wx-card-list">
          <button className="wx-setting-row link wx-account-entry" type="button" onClick={onOpenAccounts}>
            <span className="wx-setting-row-icon"><AccountsIcon /></span>
            <span>{t('whatsappAccounts')}</span>
            <span className="wx-setting-value">
              {accountSummary?.online || 0}/{accountSummary?.total || 0} {t('online')}
            </span>
            <span aria-hidden="true">›</span>
          </button>
        </div>
      </div>

      <div className="wx-cell-group">
        <div className="wx-cell-group-title">{t('globalAi')}</div>
        <div className="wx-section-list wx-card-list">
          <button className="wx-setting-row link wx-ai-entry" type="button" onClick={onOpenGlobalAi}>
            <span className="wx-setting-row-icon"><AiIcon /></span>
            <span>
              <strong>{t('globalAiSettings')}</strong>
              <small>{aiSummary?.model || t('notConfigured')}</small>
            </span>
            <span className={`pill ${aiSummary?.configured ? 'ok' : 'muted'}`}>
              {aiSummary?.configured ? t('enabled') : t('notConfigured')}
            </span>
            <span aria-hidden="true">›</span>
          </button>
          <button className="wx-setting-row link" type="button" onClick={onOpenGlobalAi}>
            <span>{t('autoTranslate')}</span>
            <span className="wx-setting-value">{autoTranslate ? t('statusOn') : t('statusOff')}</span>
            <span aria-hidden="true">›</span>
          </button>
        </div>
      </div>

      <div className="wx-cell-group">
        <div className="wx-cell-group-title">{t('servicesTitle')}</div>
        <div className="wx-section-list wx-card-list">
          <button className="wx-setting-row link" type="button" onClick={onOpenPlugins}>
            <span className="wx-setting-row-icon"><PluginsIcon /></span>
            <span>{t('pluginCenter')}</span>
            <span aria-hidden="true">›</span>
          </button>
          <button className="wx-setting-row link" type="button" onClick={onOpenSettings}>
            <span>{t('settings')}</span>
            <span aria-hidden="true">›</span>
          </button>
        </div>
      </div>

      <div className="wx-cell-group">
        <div className="wx-cell-group-title">{t('preferencesTitle')}</div>
        <div className="wx-section-list wx-card-list">
          <label className="wx-setting-row wx-setting-row-form">
            <span>{t('language')}</span>
            <select value={language} onChange={e => setLanguage(e.target.value)}>
              {languages.map(l => (
                <option key={l.code} value={l.code}>{l.label}</option>
              ))}
            </select>
          </label>
          <div className="wx-setting-row wx-setting-row-form">
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
          </div>
        </div>
      </div>

      <div className="wx-cell-group">
        <div className="wx-section-list wx-card-list">
          <button className="wx-setting-row link danger" type="button" onClick={onLogout}>
            <span>{t('logout')}</span>
            <span aria-hidden="true">›</span>
          </button>
        </div>
      </div>
    </section>
  )
}
