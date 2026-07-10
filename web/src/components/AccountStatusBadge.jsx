import { useSettings } from '../settings'
import { statusMeta } from '../accounts/accountState'

export default function AccountStatusBadge({ status, enabled = true }) {
  const { t } = useSettings()
  const meta = statusMeta(status)
  const label = enabled ? t(meta.key) : t('accountDisabled')
  return (
    <span className={`wx-account-status ${enabled ? meta.tone : 'disabled'}`}>
      <span className="wx-account-status-dot" aria-hidden="true" />
      {label}
    </span>
  )
}
