import { useState, useEffect } from 'react'
import { useSettings } from '../settings'
import { api } from '../api'

export default function UserManagementPage({ onClose, onSwitchUser }) {
  const { t } = useSettings()
  const [users, setUsers] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [tab, setTab] = useState('list') // 'list' | 'add'
  const [newUsername, setNewUsername] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPwd, setConfirmPwd] = useState('')
  const [addError, setAddError] = useState('')
  const [addLoading, setAddLoading] = useState(false)
  const [addSuccess, setAddSuccess] = useState('')
  const [deleteConfirm, setDeleteConfirm] = useState('')

  const loadUsers = async () => {
    setLoading(true)
    setError('')
    try {
      const data = await api.get('/v1/users')
      setUsers(Array.isArray(data) ? data : [])
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  const handleAdd = async e => {
    e.preventDefault()
    setAddError('')
    if (!newUsername.trim()) { setAddError(t('usernameRequired') || 'Username required'); return }
    if (!/^[a-zA-Z0-9_-]+$/.test(newUsername.trim())) {
      setAddError(t('usernameInvalidChars') || 'Invalid username')
      return
    }
    if (newPassword.length < 8) { setAddError(t('passwordTooShort') || 'Min 8 chars'); return }
    if (newPassword !== confirmPwd) { setAddError(t('passwordMismatch') || 'Passwords do not match'); return }
    setAddLoading(true)
    try {
      await api.post('/v1/users/register', { username: newUsername.trim(), password: newPassword })
      setAddSuccess(t('userCreated') || 'User created successfully')
      setNewUsername('')
      setNewPassword('')
      setConfirmPwd('')
      await loadUsers()
      setTimeout(() => { setAddSuccess(''); setTab('list') }, 1500)
    } catch (e) {
      setAddError(e.message)
    } finally {
      setAddLoading(false)
    }
  }

  const handleDelete = async username => {
    if (deleteConfirm !== username) { setDeleteConfirm(username); return }
    try {
      await api.post('/v1/users/delete', { username })
      setDeleteConfirm('')
      await loadUsers()
    } catch (e) {
      setError(e.message)
    }
  }

  // Load users on mount
  useEffect(() => { loadUsers() }, [])

  return (
    <div className="modal wx-ump">
      <div className="modal-header wx-ump-header">
        <button className="wx-icon-btn wx-ump-back" onClick={onClose}>
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
            <path d="M19 12H5M12 5l-7 7 7 7"/>
          </svg>
        </button>
        <h2 className="wx-ump-title">{t('userManagement') || 'User Management'}</h2>
        <button className="wx-btn-outline wx-ump-add-btn" onClick={() => { setTab('add'); setAddError(''); setAddSuccess('') }}>
          + {t('addUser') || 'Add User'}
        </button>
      </div>

      {/* Tabs */}
      {tab === 'list' && (
        <div className="wx-ump-body">
          {loading ? (
            <div className="wx-ump-loading">{t('loading') || 'Loading…'}</div>
          ) : error ? (
            <div className="wx-ump-error">{error}</div>
          ) : (
            <div className="wx-ump-list">
              {users.map(u => (
                <div key={u.username} className="wx-ump-user-row">
                  <div className="wx-ump-user-info">
                    <div className="wx-ump-avatar">{u.username.slice(0, 1).toUpperCase()}</div>
                    <div>
                      <div className="wx-ump-username">{u.username}</div>
                      <div className="wx-ump-created">
                        {t('createdAt') || 'Created'}: {new Date(u.created_at * 1000).toLocaleDateString()}
                      </div>
                    </div>
                  </div>
                  <button
                    className={`wx-btn-danger-outline ${deleteConfirm === u.username ? 'confirm' : ''}`}
                    onClick={() => handleDelete(u.username)}
                    onBlur={() => setTimeout(() => setDeleteConfirm(''), 200)}
                  >
                    {deleteConfirm === u.username
                      ? (t('confirmDelete') || 'Confirm delete?')
                      : (t('delete') || 'Delete')}
                  </button>
                </div>
              ))}
              {users.length === 0 && (
                <div className="wx-ump-empty">{t('noUsers') || 'No users yet'}</div>
              )}
            </div>
          )}
        </div>
      )}

      {tab === 'add' && (
        <div className="wx-ump-body">
          <form className="wx-ump-form" onSubmit={handleAdd}>
            <div className="wx-field">
              <label className="wx-field-label">{t('usernameLabel')}</label>
              <input
                type="text"
                className="wx-field-input"
                value={newUsername}
                onChange={e => setNewUsername(e.target.value)}
                placeholder={t('usernamePlaceholder')}
                autoFocus
              />
            </div>
            <div className="wx-field">
              <label className="wx-field-label">{t('passwordLabel')}</label>
              <input
                type="password"
                className="wx-field-input"
                value={newPassword}
                onChange={e => setNewPassword(e.target.value)}
                placeholder={t('newPasswordPlaceholder')}
              />
            </div>
            <div className="wx-field">
              <label className="wx-field-label">{t('confirmPasswordLabel')}</label>
              <input
                type="password"
                className="wx-field-input"
                value={confirmPwd}
                onChange={e => setConfirmPwd(e.target.value)}
                placeholder={t('confirmPasswordPlaceholder')}
              />
            </div>
            {addError ? <div className="wx-auth-error">{addError}</div> : null}
            {addSuccess ? <div className="wx-ump-success">{addSuccess}</div> : null}
            <div className="wx-ump-form-actions">
              <button type="button" className="wx-btn-outline" onClick={() => setTab('list')}>
                {t('cancel') || 'Cancel'}
              </button>
              <button type="submit" className="wx-btn-primary" disabled={addLoading}>
                {addLoading ? (t('creatingAccount') || 'Creating…') : (t('createUser') || 'Create User')}
              </button>
            </div>
          </form>
        </div>
      )}
    </div>
  )
}
