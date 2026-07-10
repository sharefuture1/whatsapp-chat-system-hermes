import { useEffect, useState } from 'react'
import { useSettings } from '../settings'

const QrIcon = () => <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM15 14h2v2h-2zM19 14h1v3h-3v3h-3v-2h2v-2h3z" /></svg>

export default function AccountQrPage({ account, onBack, onLoadQr }) {
  const { t } = useSettings()
  const [qr, setQr] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = async () => {
    setLoading(true)
    setError('')
    try {
      setQr(await onLoadQr(account.id))
    } catch (err) {
      setError(err?.data?.error?.code || err?.message || 'qr_failed')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [account.id]) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <section className="wx-account-page wx-account-qr-page">
      <header className="wx-account-page-header">
        <button className="wx-icon-btn" onClick={onBack} aria-label={t('back')}>
          <svg viewBox="0 0 24 24"><path d="m15 5-7 7 7 7" /></svg>
        </button>
        <h2>{t('accountScanTitle')}</h2>
        <span className="wx-account-header-spacer" />
      </header>
      <div className="wx-account-qr-content" aria-live="polite">
        <div className="wx-account-qr-brand"><QrIcon /></div>
        <h3>{account.name}</h3>
        <p>{t('accountScanHelp')}</p>
        <div className="wx-account-qr-box">
          {loading ? <div className="wx-spinner" aria-label={t('loading')} /> : null}
          {!loading && qr?.qr_data_url ? <img src={qr.qr_data_url} alt={t('accountQrAlt')} /> : null}
          {!loading && !qr?.qr_data_url ? <div className="wx-account-qr-empty">{error || t('accountQrUnavailable')}</div> : null}
        </div>
        {qr?.expires_at ? <p className="wx-account-qr-expiry">{t('accountQrExpiry')}：{new Date(qr.expires_at).toLocaleTimeString()}</p> : null}
        {error ? <button className="wx-primary-btn" onClick={load}>{t('retry')}</button> : null}
      </div>
    </section>
  )
}
