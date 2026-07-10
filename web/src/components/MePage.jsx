import { useSettings } from '../settings'

export default function MePage({ health, onOpenSettings, onLogout, profilePath, autoTranslate, profileSummary }) {
  const { t, language, setLanguage, languages, theme, toggleTheme } = useSettings()
  return (
    <section className="wx-page wx-me-page">
      <div className="wx-me-hero">
        <div className="wx-avatar lg" style={{ background: '#07c160' }}>我</div>
        <div className="wx-me-hero-meta">
          <div className="wx-me-name">{t('operator')}</div>
          <div className="wx-me-sub">{profilePath || (health?.profile ?? '-')}</div>
          <div className="wx-me-status-row">
            <span className={`pill ${health ? 'ok' : 'muted'}`}>{health ? t('online') : t('offline')}</span>
            <span className="pill muted">{autoTranslate ? t('autoTranslate') : `${t('autoTranslate')} · ${t('statusOff')}`}</span>
          </div>
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
        <div className="wx-cell-group-title">{t('activeConversation') || '当前聊天对象'}</div>
        <div className="wx-section-list wx-card-list">
          <div className="wx-setting-row"><span>{t('activeConversation') || '当前会话'}</span><span className="wx-setting-value">{profileSummary?.userName || '—'}</span></div>
          <div className="wx-setting-row"><span>{t('contactId') || '联系人ID'}</span><span className="wx-setting-value wx-mono">{profileSummary?.userId || '—'}</span></div>
          <div className="wx-setting-row multi"><span>{t('contactNotes') || '联系人说明'}</span><span className="wx-setting-value wx-multiline">{profileSummary?.notes || '—'}</span></div>
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
