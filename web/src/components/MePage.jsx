import { useSettings } from '../settings'

export default function MePage({ health, onOpenSettings, onLogout, profilePath, autoTranslate }) {
  const { t, language, setLanguage, languages, theme, toggleTheme } = useSettings()
  return (
    <section className="wx-page">
      <div className="wx-me-header">
        <div className="wx-avatar lg" style={{ background: '#07c160' }}>我</div>
        <div>
          <div className="wx-me-name">Operator</div>
          <div className="wx-me-sub">{profilePath || (health?.profile ?? '-')}</div>
        </div>
      </div>
      <div className="wx-section-list">
        <div className="wx-setting-row"><span>{t('language')}</span><select value={language} onChange={e => setLanguage(e.target.value)}>{languages.map(l => <option key={l.code} value={l.code}>{l.label}</option>)}</select></div>
        <div className="wx-setting-row"><span>{t('theme')}</span><button className="wx-inline-btn" onClick={toggleTheme}>{theme === 'light' ? t('themeLight') : t('themeDark')}</button></div>
        <div className="wx-setting-row"><span>{t('autoTranslate')}</span><span className="wx-setting-value">{autoTranslate ? 'ON' : 'OFF'}</span></div>
        <button className="wx-setting-row link" onClick={onOpenSettings}><span>{t('settings')}</span><span>›</span></button>
        <button className="wx-setting-row link danger" onClick={onLogout}><span>{t('logout')}</span><span>›</span></button>
      </div>
    </section>
  )
}
