const STATUS = {
  new: { key: 'accountStatusNew', tone: 'neutral' },
  qr_pending: { key: 'accountStatusQrPending', tone: 'pending' },
  connecting: { key: 'accountStatusConnecting', tone: 'pending' },
  online: { key: 'accountStatusOnline', tone: 'online' },
  offline: { key: 'accountStatusOffline', tone: 'offline' },
  error: { key: 'accountStatusError', tone: 'error' },
  logged_out: { key: 'accountStatusLoggedOut', tone: 'error' },
}

export function statusMeta(status) {
  return STATUS[status] || { key: 'accountStatusUnknown', tone: 'neutral' }
}

export function normalizeAccount(value = {}) {
  return {
    id: String(value.id || ''),
    name: String(value.name || ''),
    phone_number: value.phone_number || null,
    status: STATUS[value.status] ? value.status : 'new',
    enabled: value.enabled !== false,
    is_primary: value.is_primary === true,
    auto_reply_mode: value.auto_reply_mode || 'off',
    ai_profile_id: value.ai_profile_id || null,
    last_seen_at: value.last_seen_at || null,
    last_error_code: value.last_error_code || null,
    last_error_message: value.last_error_message || null,
    created_at: value.created_at || null,
    updated_at: value.updated_at || null,
  }
}

export function mergeAccountEvent(accounts, event, seenEvents = new Set()) {
  if (!event?.event_id || seenEvents.has(event.event_id)) return { accounts, applied: false }
  const index = accounts.findIndex(item => item.id === event.account_id)
  if (index < 0) return { accounts, applied: false }
  const current = accounts[index]
  const eventTime = Date.parse(event.occurred_at || '') || 0
  const currentTime = Date.parse(current.updated_at || '') || 0
  if (eventTime && currentTime && eventTime < currentTime) return { accounts, applied: false }
  seenEvents.add(event.event_id)
  const next = [...accounts]
  next[index] = normalizeAccount({
    ...current,
    ...(event.payload || {}),
    updated_at: event.occurred_at || current.updated_at,
  })
  return { accounts: next, applied: true }
}

export function summarizeAccounts(accounts = []) {
  return accounts.reduce((summary, item) => {
    summary.total += 1
    if (item.enabled) summary.enabled += 1
    if (item.status === 'online') summary.online += 1
    if (item.status === 'error' || item.status === 'logged_out') summary.attention += 1
    return summary
  }, { total: 0, online: 0, attention: 0, enabled: 0 })
}
