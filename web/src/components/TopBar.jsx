import { useEffect, useState } from 'react'
import { api } from '../api'
import { useSettings } from '../settings'
import { fmtTime } from '../format'

export default function TopBar({ health, onRunJob, runningJob, onLogout, onOpenSettings, onOpenMobileNav }) {
  const { t, language, setLanguage, languages, theme, toggleTheme } = useSettings()
  const [banner, setBanner] = useState(null)
  useEffect(() => {
    if (!banner) return
    const id = setTimeout(() => setBanner(null), 2500)
    return () => clearTimeout(id)
  }, [banner])
  return (
    <header className="appbar">
      <div className="appbar-left">
        <button className="icon-btn mobile-only" aria-label="Menu" onClick={onOpenMobileNav}>
          <span aria-hidden="true">☰</span>
        </button>
        <div className="appbar-brand">
          <div className="appbar-eyebrow">{t('appEyebrow')}</div>
          <div className="appbar-title">{t('appTitle')}</div>
          <div className="appbar-workspace subtle">
            {health ? `${t('workspace')}: ${health.profile}` : `${t('loading')}…`}
          </div>
        </div>
      </div>
      <div className="appbar-right">
        <span className={`status-dot ${health ? 'online' : 'offline'}`} aria-label={health ? t('online') : t('offline')}>
          <span className="dot" /> {health ? t('online') : t('offline')}
        </span>
        <label className="lang-picker" aria-label={t('language')}>
          <span className="lang-picker-icon" aria-hidden="true">🌐</span>
          <select value={language} onChange={e => setLanguage(e.target.value)}>
            {languages.map(l => <option key={l.code} value={l.code}>{l.label}</option>)}
          </select>
        </label>
        <button className="icon-btn" aria-label={t('theme')} title={t('theme')} onClick={toggleTheme}>
          <span aria-hidden="true">{theme === 'light' ? '☀' : '☾'}</span>
        </button>
        <button className="icon-btn" aria-label={t('settings')} title={t('settings')} onClick={onOpenSettings}>
          <span aria-hidden="true">⚙</span>
        </button>
        <button className="icon-btn danger" aria-label={t('logout')} title={t('logout')} onClick={onLogout}>
          <span aria-hidden="true">⏻</span>
        </button>
      </div>
      {banner ? <div className="appbar-toast" role="status">{banner}</div> : null}
    </header>
  )
}
