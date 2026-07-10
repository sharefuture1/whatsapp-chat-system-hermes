import { useSettings } from '../settings'

const AccountsIcon = () => <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 3h10a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2Z"/><path d="M10 18h4"/></svg>
const OperatorIcon = () => <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="8" r="4"/><path d="M4 21c0-4 3.6-7 8-7s8 3 8 7"/></svg>

export default function MePage({ health, onOpenSettings, onOpenGlobalAi, onOpenAccounts, onLogout, autoTranslate, accountSummary, aiSummary }) {
  const { t, language, setLanguage, languages, theme, toggleTheme } = useSettings()
  return (
    <section className="wx-page wx-me-page">
      <div className="wx-me-hero">
        <div className="wx-avatar lg wx-operator-avatar" style={{ background: '#07c160' }}><OperatorIcon /></div>
        <div className="wx-me-hero-meta">
          <div className="wx-me-name">{t('operator')}</div>
          <div className="wx-me-sub">{t('operatorRole')}</div>
          <div className="wx-me-status-row">
            <span className={`pill ${health ? 'ok' : 'muted'}`}>{health ? t('serviceOnline') : t('serviceOffline')}</span>
            <span className="pill muted">{autoTranslate ? t('autoTranslate') : `${t('autoTranslate')} · ${t('statusOff')}`}</span>
          </div>
        </div>
      </div>

      <div className="wx-cell-group">
        <div className="wx-cell-group-title">{t('accountAndConnection')}</div>
        <div className="wx-section-list wx-card-list">
          <button className="wx-setting-row link wx-account-entry" onClick={onOpenAccounts}>
            <span className="wx-setting-row-icon"><AccountsIcon /></span>
            <span>{t('whatsappAccounts')}</span>
            <span className="wx-setting-value">{accountSummary?.online || 0}/{accountSummary?.total || 0} {t('online')}</span>
            <span>›</span>
          </button>
        </div>
      </div>

      <div className="wx-cell-group">
        <div className="wx-cell-group-title">{t('globalAi') || '全局 AI'}</div>
        <div className="wx-section-list wx-card-list">
          <button className="wx-setting-row link wx-ai-entry" onClick={onOpenGlobalAi}>
            <span className="wx-setting-row-icon"><svg viewBox="0 0 24 24"><path d="M12 3a7 7 0 0 1 7 7v4a3 3 0 0 1-3 3h-1l-3 3-3-3H8a3 3 0 0 1-3-3v-4a7 7 0 0 1 7-7Z"/><path d="M9 10h.01M15 10h.01M9.5 14h5"/></svg></span>
            <span><strong>{t('globalAiSettings') || '全局 AI 设置'}</strong><small>{aiSummary?.model || t('notConfigured') || '未配置模型'}</small></span>
            <span className={`pill ${aiSummary?.configured ? 'ok' : 'muted'}`}>{aiSummary?.configured ? t('enabled') : t('notConfigured')}</span>
            <span>›</span>
          </button>
          <button className="wx-setting-row link" onClick={onOpenGlobalAi}><span>{t('autoTranslate')}</span><span className="wx-setting-value">{autoTranslate ? t('statusOn') : t('statusOff')}</span><span>›</span></button>
        </div>
      </div>

      <div className="wx-cell-group">
        <div className="wx-cell-group-title">{t('settings')}</div>
        <div className="wx-section-list wx-card-list">
          <button className="wx-setting-row link" onClick={onOpenSettings}><span>{t('settings')}</span><span>›</span></button>
          <label className="wx-setting-row wx-setting-row-form">
            <span>{t('language')}</span>
            <select value={language} onChange={e => setLanguage(e.target.value)}>
              {languages.map(l => <option key={l.code} value={l.code}>{l.label}</option>)}
            </select>
          </label>
          <button className="wx-setting-row link" onClick={toggleTheme}><span>{t('theme')}</span><span className="wx-setting-value">{theme === 'light' ? t('themeLight') : t('themeDark')}</span></button>
        </div>
      </div>

      <div className="wx-cell-group">
        <div className="wx-cell-group-title">{t('security')}</div>
        <div className="wx-section-list wx-card-list">
          <button className="wx-setting-row link danger" onClick={onLogout}><span>{t('logout')}</span><span>›</span></button>
        </div>
      </div>
    </section>
  )
}
