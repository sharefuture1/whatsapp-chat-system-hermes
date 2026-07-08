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
    <div className="login-shell">
      <form className="login-card" onSubmit={submit}>
        <div className="login-brand">
          <div className="appbar-eyebrow">{t('secureAccess')}</div>
          <h1>{t('loginTitle')}</h1>
        </div>
        <div className="subtle login-subtitle">{t('loginSubtitle')}</div>
        <label className="login-label">
          <span className="login-label-text">{t('passwordPlaceholder')}</span>
          <input
            type="password"
            value={password}
            onChange={e => setPassword(e.target.value)}
            placeholder={t('passwordPlaceholder')}
            autoFocus
            autoComplete="current-password"
          />
        </label>
        {error ? <div className="error-text">{error}</div> : null}
        <button type="submit" disabled={loading || !password}>
          {loading ? t('signingIn') : t('signIn')}
        </button>
      </form>
    </div>
  )
}
