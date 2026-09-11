import { useState } from 'react'
import { api } from '../api'
import { useSettings } from '../settings'

export default function PasswordChangeScreen({ onLogout }) {
  const { t } = useSettings()
  const [oldPassword, setOldPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmation, setConfirmation] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const submit = async event => {
    event.preventDefault()
    if (busy) return
    if (newPassword.length < 8) { setError(t('passwordTooShort')); return }
    if (newPassword !== confirmation) { setError(t('passwordMismatch')); return }
    setBusy(true)
    setError('')
    try {
      await api.post('/v1/users/change-password', { old_password: oldPassword, new_password: newPassword })
      setOldPassword('')
      setNewPassword('')
      setConfirmation('')
      await onLogout()
    } catch (failure) {
      if (!['stale_session', 'request_cancelled'].includes(failure?.code)) setError(failure?.message || t('error'))
    } finally { setBusy(false) }
  }

  return <main className="wx-auth-shell wx-force-password">
    <section className="wx-auth-card">
      <h1>{t('changePassword')}</h1>
      <p>{t('passwordChangeRequired')}</p>
      <form className="wx-auth-form" data-testid="force-password" onSubmit={submit} aria-busy={busy}>
        <div className="wx-field">
          <label className="wx-field-label" htmlFor="required-old-password">{t('currentPasswordLabel')}</label>
          <div className="wx-field-input-wrap"><input id="required-old-password" name="old_password" type="password" autoComplete="current-password" required maxLength={128} value={oldPassword} onChange={e => setOldPassword(e.target.value)} /></div>
        </div>
        <div className="wx-field">
          <label className="wx-field-label" htmlFor="required-new-password">{t('newPassword')}</label>
          <div className="wx-field-input-wrap"><input id="required-new-password" name="new_password" type="password" autoComplete="new-password" required minLength={8} maxLength={128} value={newPassword} onChange={e => setNewPassword(e.target.value)} /></div>
        </div>
        <div className="wx-field">
          <label className="wx-field-label" htmlFor="required-confirm-password">{t('confirmPasswordLabel')}</label>
          <div className="wx-field-input-wrap"><input id="required-confirm-password" name="confirm_password" type="password" autoComplete="new-password" required minLength={8} maxLength={128} value={confirmation} onChange={e => setConfirmation(e.target.value)} /></div>
        </div>
        {error ? <p role="alert">{error}</p> : null}
        <button className="wx-btn-primary" type="submit" disabled={busy}>{busy ? t('saving') : t('save')}</button>
        <button className="wx-btn" type="button" onClick={onLogout}>{t('logout')}</button>
      </form>
    </section>
  </main>
}
