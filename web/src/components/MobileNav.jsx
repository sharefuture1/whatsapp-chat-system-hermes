import { useSettings } from '../settings'

const TABS = [
  { id: 'inbox', icon: '✉' },
  { id: 'detail', icon: '💬' },
  { id: 'profile', icon: '👤' },
  { id: 'channels', icon: '📡' },
  { id: 'aliases', icon: '🗂' },
]

export default function MobileNav({ open, onClose, activeTab, onChange }) {
  const { t, language, setLanguage, languages, theme, toggleTheme } = useSettings()
  if (!open) return null
  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" onClick={onClose}>
      <div className="mobile-nav-drawer" onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <h2>{t('appTitle')}</h2>
          <button className="icon-btn" aria-label={t('dismiss')} onClick={onClose}>
            <span aria-hidden="true">✕</span>
          </button>
        </div>
        <nav className="mobile-nav-list">
          {TABS.map(tab => (
            <button
              key={tab.id}
              className={`mobile-nav-item ${activeTab === tab.id ? 'active' : ''}`}
              onClick={() => onChange(tab.id)}
            >
              <span className="mobile-nav-icon" aria-hidden="true">{tab.icon}</span>
              <span>{t(`nav${tab.id.charAt(0).toUpperCase()}${tab.id.slice(1)}`)}</span>
            </button>
          ))}
        </nav>
        <div className="mobile-nav-controls">
          <label className="field">
            <span>{t('language')}</span>
            <select value={language} onChange={e => setLanguage(e.target.value)}>
              {languages.map(l => <option key={l.code} value={l.code}>{l.label}</option>)}
            </select>
          </label>
          <button className="ghost-btn" onClick={toggleTheme}>
            {t('theme')}: {theme === 'light' ? t('themeLight') : t('themeDark')}
          </button>
        </div>
      </div>
    </div>
  )
}
