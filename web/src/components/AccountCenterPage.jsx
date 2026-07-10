import { useState } from 'react'
import { useSettings } from '../settings'
import AccountQrPage from './AccountQrPage'
import AccountStatusBadge from './AccountStatusBadge'

const AddIcon = () => <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14M5 12h14" /></svg>
const PhoneIcon = () => <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 3h10a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2Z"/><path d="M10 18h4"/></svg>

function AccountRow({ account, onOpen }) {
  const { t } = useSettings()
  return (
    <button className="wx-account-row" onClick={() => onOpen(account)}>
      <span className="wx-account-avatar"><PhoneIcon /></span>
      <span className="wx-account-row-main">
        <span className="wx-account-row-title">
          <strong>{account.name}</strong>
          {account.is_primary ? <span className="wx-account-primary">{t('accountPrimary')}</span> : null}
        </span>
        <small>{account.phone_number || t('accountNoPhone')}</small>
      </span>
      <AccountStatusBadge status={account.status} enabled={account.enabled} />
      <span className="wx-cell-chevron">›</span>
    </button>
  )
}

function AccountDetail({ account, actions, onBack, onQr }) {
  const { t } = useSettings()
  const [busy, setBusy] = useState('')
  const run = async (name, fn) => {
    setBusy(name)
    try {
      await fn()
      return true
    } catch (err) {
      window.alert(err?.message || t('error'))
      return false
    } finally { setBusy('') }
  }
  const remove = async deleteSession => {
    const confirmation = window.prompt(t('accountDeleteConfirmPrompt').replace('{name}', account.name))
    if (confirmation !== account.name) return
    const deleted = await run('delete', () => actions.remove(account.id, { confirm_name: confirmation, delete_session: deleteSession }))
    if (deleted) onBack()
  }
  return (
    <section className="wx-account-page">
      <header className="wx-account-page-header">
        <button className="wx-icon-btn" onClick={onBack} aria-label={t('back')}><svg viewBox="0 0 24 24"><path d="m15 5-7 7 7 7" /></svg></button>
        <h2>{account.name}</h2><span className="wx-account-header-spacer" />
      </header>
      <div className="wx-account-detail-hero">
        <span className="wx-account-avatar lg"><PhoneIcon /></span>
        <h3>{account.name}</h3>
        <AccountStatusBadge status={account.status} enabled={account.enabled} />
        <p>{account.phone_number || t('accountNoPhone')}</p>
      </div>
      <div className="wx-cell-group">
        <div className="wx-cell-group-title">{t('accountConnection')}</div>
        <div className="wx-section-list">
          <button className="wx-setting-row link" disabled={busy} onClick={() => run('connect', async () => { await actions.connect(account.id); onQr(account) })}>
            <span>{account.status === 'online' ? t('accountReconnect') : t('accountStartLogin')}</span><span>›</span>
          </button>
          <button className="wx-setting-row link" disabled={busy || account.status === 'logged_out'} onClick={() => run('logout', () => actions.logout(account.id))}>
            <span>{t('accountLogoutWhatsApp')}</span><span>›</span>
          </button>
          <button className="wx-setting-row link" disabled={busy} onClick={() => run('enabled', () => actions.update(account.id, { enabled: !account.enabled }))}>
            <span>{account.enabled ? t('accountDisable') : t('accountEnable')}</span><span>›</span>
          </button>
          {!account.is_primary ? <button className="wx-setting-row link" disabled={busy} onClick={() => run('primary', () => actions.update(account.id, { is_primary: true }))}><span>{t('accountSetPrimary')}</span><span>›</span></button> : null}
        </div>
      </div>
      <div className="wx-cell-group wx-account-danger-zone">
        <div className="wx-cell-group-title">{t('accountDangerZone')}</div>
        <div className="wx-section-list">
          <button className="wx-setting-row link danger" disabled={busy} onClick={() => remove(false)}><span>{t('accountDeleteBusiness')}</span><span>›</span></button>
          <button className="wx-setting-row link danger" disabled={busy} onClick={() => remove(true)}><span>{t('accountDeleteCredentials')}</span><span>›</span></button>
        </div>
      </div>
    </section>
  )
}

export default function AccountCenterPage({ controller, onBack }) {
  const { t } = useSettings()
  const [page, setPage] = useState({ type: 'list', account: null })
  const [creating, setCreating] = useState(false)

  const createAccount = async () => {
    const name = window.prompt(t('accountNamePrompt'))?.trim()
    if (!name) return
    setCreating(true)
    try {
      await controller.create({ name, auto_reply_mode: 'off' })
    } catch (err) {
      window.alert(err?.message || t('accountCreateUnavailable'))
    } finally { setCreating(false) }
  }

  if (page.type === 'qr') return <AccountQrPage account={page.account} onBack={() => setPage({ type: 'detail', account: page.account })} onLoadQr={controller.getQr} />
  if (page.type === 'detail') {
    const fresh = controller.accounts.find(item => item.id === page.account.id) || page.account
    return <AccountDetail account={fresh} actions={controller} onBack={() => setPage({ type: 'list', account: null })} onQr={account => setPage({ type: 'qr', account })} />
  }

  return (
    <section className="wx-account-page">
      <header className="wx-account-page-header">
        <button className="wx-icon-btn" onClick={onBack} aria-label={t('back')}><svg viewBox="0 0 24 24"><path d="m15 5-7 7 7 7" /></svg></button>
        <h2>{t('whatsappAccounts')}</h2>
        <button className="wx-icon-btn" onClick={createAccount} disabled={creating} aria-label={t('accountAdd')}><AddIcon /></button>
      </header>
      <div className="wx-account-summary" aria-live="polite">
        <strong>{controller.summary.online}</strong> {t('accountOnlineOf')} {controller.summary.total}
        {controller.summary.attention ? <span>{controller.summary.attention} {t('accountNeedAttention')}</span> : null}
      </div>
      {controller.loading ? <div className="wx-account-loading"><span className="wx-spinner" />{t('loading')}</div> : null}
      {controller.error ? <button className="wx-account-error" onClick={() => controller.refresh()}>{t('accountLoadFailed')} · {t('retry')}</button> : null}
      <div className="wx-section-list wx-account-list">
        {controller.accounts.map(account => <AccountRow key={account.id} account={account} onOpen={item => setPage({ type: 'detail', account: item })} />)}
        {!controller.loading && controller.accounts.length === 0 ? <div className="wx-account-empty"><PhoneIcon /><h3>{t('accountEmptyTitle')}</h3><p>{t('accountEmptyHelp')}</p></div> : null}
      </div>
      <div className="wx-account-add-bar"><button className="wx-primary-btn" onClick={createAccount} disabled={creating}><AddIcon />{creating ? t('saving') : t('accountAdd')}</button></div>
    </section>
  )
}
