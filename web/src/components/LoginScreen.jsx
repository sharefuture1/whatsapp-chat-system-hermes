import { useState } from 'react'
import { useSettings } from '../settings'

export default function LoginScreen({ onLogin, error, loading }) {
  const { t } = useSettings()
  const [password, setPassword] = useState('')
  const submit = e => {
    e.preventDefault()
    if (password && !loading) onLogin(password)
  }
  return (
    <div className="wx-login-shell">
      <div className="wx-login-hero">
        <div className="wx-login-brand-mark">微</div>
        <div className="wx-login-brand-copy">
          <div className="wx-login-eyebrow">{t('secureAccess')}</div>
          <h1>{t('appTitle')}</h1>
          <p>{t('loginSubtitle')}</p>
        </div>
      </div>
      <form className="wx-login-card" onSubmit={submit}>
        <div className="wx-login-title">{t('loginTitle')}</div>
        <label className="wx-login-label">
          <span>{t('passwordPlaceholder')}</span>
          <input
            type="password"
            value={password}
            onChange={e => setPassword(e.target.value)}
            placeholder={t('passwordPlaceholder')}
            autoFocus
            autoComplete="current-password"
          />
        </label>
        {error ? <div className="wx-login-error">{error}</div> : null}
        <button className="wx-login-submit" type="submit" disabled={loading || !password}>
          {loading ? t('signingIn') : t('signIn')}
        </button>
      </form>
    </div>
  )
}
