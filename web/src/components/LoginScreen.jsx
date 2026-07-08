import { useState } from 'react'

export default function LoginScreen({ onLogin, error, loading }) {
  const [password, setPassword] = useState('')
  const submit = e => {
    e.preventDefault()
    if (password && !loading) onLogin(password)
  }
  return (
    <div className="login-shell">
      <form className="login-card" onSubmit={submit}>
        <div className="eyebrow">Secure Access</div>
        <h1>Operator Login</h1>
        <div className="subtle">Enter the console password to access conversations and controls.</div>
        <input type="password" value={password} onChange={e => setPassword(e.target.value)} placeholder="Console password" autoFocus />
        {error ? <div className="error-text">{error}</div> : null}
        <button type="submit" disabled={loading || !password}>{loading ? 'Signing in...' : 'Sign in'}</button>
      </form>
    </div>
  )
}
