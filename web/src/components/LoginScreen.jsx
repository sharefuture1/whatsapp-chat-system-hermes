import { useState } from 'react'
import { useSettings } from '../settings'

export default function LoginScreen({ onLogin, onRegister, error, loading }) {
  const { t } = useSettings()
  const [mode, setMode] = useState('login') // 'login' | 'register'
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [localError, setLocalError] = useState('')

  const handleSubmit = e => {
    e.preventDefault()
    setLocalError('')
    if (!username.trim()) { setLocalError(t('usernameRequired') || 'Username is required'); return }
    if (username.trim().length < 3) { setLocalError(t('usernameTooShort') || 'Username must be at least 3 characters'); return }
    if (!/^[a-zA-Z0-9_-]+$/.test(username.trim())) {
      setLocalError(t('usernameInvalidChars') || 'Only letters, numbers, _ and - are allowed')
      return
    }
    if (!password) { setLocalError(t('passwordRequired') || 'Password is required'); return }
    if (password.length < 8) { setLocalError(t('passwordTooShort') || 'Password must be at least 8 characters'); return }
    if (mode === 'register' && password !== confirmPassword) {
      setLocalError(t('passwordMismatch') || 'Passwords do not match')
      return
    }
    const credentials = { username: username.trim(), password }
    if (mode === 'register') {
      onRegister(credentials)
    } else {
      onLogin(credentials)
    }
  }

  const switchMode = m => {
    setMode(m)
    setLocalError('')
    setPassword('')
    setConfirmPassword('')
  }

  return (
    <div className="wx-auth-shell">
      {/* Left panel — brand */}
      <div className="wx-auth-left">
        <div className="wx-auth-brand">
          <div className="wx-auth-logo">
            <svg viewBox="0 0 40 40" fill="none" xmlns="http://www.w3.org/2000/svg">
              <rect width="40" height="40" rx="10" fill="white" fillOpacity="0.18"/>
              <path d="M12 14C12 12.9 12.9 12 14 12H26C27.1 12 28 12.9 28 14V22C28 23.1 27.1 24 26 24H18L14 28V14Z" stroke="white" strokeWidth="1.8" strokeLinejoin="round"/>
              <circle cx="17" cy="18" r="1.5" fill="white"/>
              <circle cx="21" cy="18" r="1.5" fill="white"/>
              <circle cx="25" cy="18" r="1.5" fill="white"/>
            </svg>
          </div>
          <h1 className="wx-auth-appname">{t('appTitle')}</h1>
          <p className="wx-auth-tagline">{t('loginTagline')}</p>
        </div>
        <div className="wx-auth-features">
          {['Multi-user access control', 'Real-time message routing', 'AI-powered translation'].map(f => (
            <div key={f} className="wx-auth-feature-item">
              <span className="wx-auth-feature-dot" />
              <span>{f}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Right panel — form */}
      <div className="wx-auth-right">
        <div className="wx-auth-card">
          {/* Tab switcher */}
          <div className="wx-auth-tabs">
            <button
              className={`wx-auth-tab${mode === 'login' ? ' active' : ''}`}
              onClick={() => switchMode('login')}
            >
              {t('signIn')}
            </button>
            <button
              className={`wx-auth-tab${mode === 'register' ? ' active' : ''}`}
              onClick={() => switchMode('register')}
            >
              {t('createAccount')}
            </button>
          </div>

          <form className="wx-auth-form" onSubmit={handleSubmit}>
            {/* Username */}
            <div className="wx-field">
              <label className="wx-field-label">{t('usernameLabel')}</label>
              <div className="wx-field-input-wrap">
                <span className="wx-field-icon">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
                    <circle cx="12" cy="8" r="4"/>
                    <path d="M4 20c0-4 3.6-7 8-7s8 3 8 7"/>
                  </svg>
                </span>
                <input
                  type="text"
                  className="wx-field-input"
                  value={username}
                  onChange={e => setUsername(e.target.value)}
                  placeholder={t('usernamePlaceholder')}
                  autoComplete="username"
                  autoFocus
                />
              </div>
            </div>

            {/* Password */}
            <div className="wx-field">
              <label className="wx-field-label">{t('passwordLabel')}</label>
              <div className="wx-field-input-wrap">
                <span className="wx-field-icon">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
                    <rect x="4" y="10" width="16" height="12" rx="2"/>
                    <path d="M8 10V7a4 4 0 018 0v3"/>
                  </svg>
                </span>
                <input
                  type="password"
                  className="wx-field-input"
                  value={password}
                  onChange={e => setPassword(e.target.value)}
                  placeholder={mode === 'register' ? t('newPasswordPlaceholder') : t('passwordPlaceholder')}
                  autoComplete={mode === 'register' ? 'new-password' : 'current-password'}
                />
              </div>
            </div>

            {/* Confirm Password (register only) */}
            {mode === 'register' && (
              <div className="wx-field">
                <label className="wx-field-label">{t('confirmPasswordLabel')}</label>
                <div className="wx-field-input-wrap">
                  <span className="wx-field-icon">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
                      <path d="M9 12l2 2 4-4"/>
                      <rect x="4" y="10" width="16" height="12" rx="2"/>
                    </svg>
                  </span>
                  <input
                    type="password"
                    className="wx-field-input"
                    value={confirmPassword}
                    onChange={e => setConfirmPassword(e.target.value)}
                    placeholder={t('confirmPasswordPlaceholder')}
                    autoComplete="new-password"
                  />
                </div>
              </div>
            )}

            {/* Error */}
            {(localError || error) ? (
              <div className="wx-auth-error">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <circle cx="12" cy="12" r="10"/>
                  <path d="M12 8v4M12 16h.01"/>
                </svg>
                {localError || error}
              </div>
            ) : null}

            {/* Submit */}
            <button
              className="wx-auth-submit"
              type="submit"
              disabled={loading || !username.trim() || !password}
            >
              {loading
                ? (mode === 'login' ? t('signingIn') : t('creatingAccount'))
                : (mode === 'login' ? t('signIn') : t('createAccount'))}
            </button>
          </form>

          {/* Footer hint */}
          <p className="wx-auth-hint">
            {mode === 'login'
              ? <>{t('noAccountHint')} <button className="wx-auth-link" onClick={() => switchMode('register')}>{t('signUp')}</button></>
              : <>{t('hasAccountHint')} <button className="wx-auth-link" onClick={() => switchMode('login')}>{t('signIn')}</button></>
            }
          </p>
        </div>
      </div>
    </div>
  )
}
