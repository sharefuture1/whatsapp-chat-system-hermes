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
  onOpenUserMgm,
  onLogout,
  autoTranslate,
  accountSummary,
  aiSummary,
  currentUser = { username: '', role: 'admin' },
}) {
  const { t, language, setLanguage, languages, theme, setTheme } = useSettings()
  const displayName = currentUser?.username || 'admin'
  const isAdmin = currentUser?.role === 'admin'
  return (
    <section className="wx-page wx-me-page">
      <header className="wx-me-hero">
        <div className="wx-avatar lg wx-operator-avatar" style={{ background: '#07c160' }}>
          <OperatorIcon />
        </div>
        <div className="wx-me-hero-meta">
          <div className="wx-me-name">{displayName}</div>
          <div className="wx-me-sub">
            {isAdmin ? t('roleAdmin') : t('roleOperator')} · {t('operatorRole')}
          </div>
          <div className="wx-me-status-row">
            <span className={`pill ${health ? 'ok' : 'muted'}`}>
              {health ? t('serviceOnline') : t('serviceOffline')}
            </span>
            <span className="pill muted">{t('autoTranslate')}</span>
            <span className="pill muted">
              {accountSummary?.online || 0}/{accountSummary?.total || 0} {t('online')}
            </span>
          </div>
        </div>
        <button type="button" className="wx-me-qr-btn" onClick={onOpenAccounts} aria-label={t('whatsappAccounts')}>
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h2v2h-2zM18 14h3v3h-3zM14 18h3v3h-3zM19 19h2v2h-2z" />
          </svg>
        </button>
      </header>

      <div className="wx-cell-group">
        <div className="wx-cell-group-title">{t('accountAndConnection')}</div>
        <div className="wx-section-list wx-card-list">
          <button className="wx-setting-row link wx-account-entry" type="button" onClick={onOpenAccounts}>
            <span className="wx-setting-row-icon"><AccountsIcon /></span>
            <span>
              <strong>{t('whatsappAccounts')}</strong>
              <small>{t('settingsSecuritySub')}</small>
            </span>
            <span className="wx-setting-value">
              {accountSummary?.online || 0}/{accountSummary?.total || 0} {t('online')}
            </span>
            <svg viewBox="0 0 24 24" aria-hidden="true" className="wx-cell-arrow"><path d="M9 6l6 6-6 6"/></svg>
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
            <svg viewBox="0 0 24 24" aria-hidden="true" className="wx-cell-arrow"><path d="M9 6l6 6-6 6"/></svg>
          </button>
          <button className="wx-setting-row link" type="button" onClick={onOpenSettings}>
            <span>{t('autoTranslate')}</span>
            <span className="wx-setting-value">{autoTranslate ? t('statusOn') : t('statusOff')}</span>
            <svg viewBox="0 0 24 24" aria-hidden="true" className="wx-cell-arrow"><path d="M9 6l6 6-6 6"/></svg>
          </button>
        </div>
      </div>

      <div className="wx-cell-group">
        <div className="wx-cell-group-title">{t('servicesTitle')}</div>
        <div className="wx-section-list wx-card-list">
          <button className="wx-setting-row link" type="button" onClick={onOpenPlugins}>
            <span className="wx-setting-row-icon"><PluginsIcon /></span>
            <span>
              <strong>{t('pluginCenter')}</strong>
              <small>{t('pluginCenterSub')}</small>
            </span>
            <svg viewBox="0 0 24 24" aria-hidden="true" className="wx-cell-arrow"><path d="M9 6l6 6-6 6"/></svg>
          </button>
          {isAdmin ? (
            <button className="wx-setting-row link" type="button" onClick={onOpenUserMgm}>
              <span className="wx-setting-row-icon">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
                  <circle cx="9" cy="7" r="4"/>
                  <path d="M4 21v-1a5 5 0 0110 0v1"/>
                  <path d="M16 3.13a4 4 0 010 7.75"/>
                  <path d="M21 21v-1a4 4 0 00-3-3.85"/>
                </svg>
              </span>
              <span>
                <strong>{t('userManagement')}</strong>
                <small>{t('userManagementSub')}</small>
              </span>
              <svg viewBox="0 0 24 24" aria-hidden="true" className="wx-cell-arrow"><path d="M9 6l6 6-6 6"/></svg>
            </button>
          ) : null}
          <button className="wx-setting-row link" type="button" onClick={onOpenSettings}>
            <span className="wx-setting-row-icon">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
                <circle cx="12" cy="12" r="3"/>
                <path d="M19 12a7 7 0 0 0-.1-1.2l2.1-1.6-2-3.4-2.4 1a7 7 0 0 0-2-1.2l-.4-2.6h-4l-.4 2.6a7 7 0 0 0-2 1.2l-2.4-1-2 3.4 2.1 1.6A7 7 0 0 0 5 12a7 7 0 0 0 .1 1.2L3 14.8l2 3.4 2.4-1a7 7 0 0 0 2 1.2l.4 2.6h4l.4-2.6a7 7 0 0 0 2-1.2l2.4 1 2-3.4-2.1-1.6c.1-.4.1-.8.1-1.2z"/>
              </svg>
            </span>
            <span>
              <strong>{t('settings')}</strong>
              <small>{t('settingsEntry')}</small>
            </span>
            <svg viewBox="0 0 24 24" aria-hidden="true" className="wx-cell-arrow"><path d="M9 6l6 6-6 6"/></svg>
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
            <svg viewBox="0 0 24 24" aria-hidden="true" className="wx-cell-arrow"><path d="M9 6l6 6-6 6"/></svg>
          </button>
        </div>
      </div>
    </section>
  )
}
