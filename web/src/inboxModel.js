function normalizePlatform(value) {
  const platform = String(value || 'whatsapp').toLowerCase()
  return platform === 'wa' ? 'whatsapp' : platform
}

export function buildInbox({ legacy = [], standalone = [], standaloneAccounts = [] } = {}) {
  const accounts = []
  const accountMap = new Map()

  if (legacy.length) {
    const account = { id: 'legacy', name: 'Legacy WhatsApp', label: 'WA1', platform: 'whatsapp', source: 'legacy', status: 'online' }
    accounts.push(account)
    accountMap.set('legacy', account)
  }

  standaloneAccounts.forEach(account => {
    const index = accounts.filter(item => item.platform === 'whatsapp').length + 1
    const normalized = {
      id: String(account.id),
      name: String(account.name || `WhatsApp ${index}`),
      label: `WA${index}`,
      platform: 'whatsapp',
      source: 'standalone',
      status: account.status || 'offline',
      enabled: account.enabled !== false,
    }
    accounts.push(normalized)
    accountMap.set(normalized.id, normalized)
  })

  const legacyItems = legacy.map(item => ({
    ...item,
    platform: normalizePlatform(item.platform),
    account_id: 'legacy',
    account_name: 'Legacy WhatsApp',
    account_label: accountMap.get('legacy')?.label || 'WA1',
    source: 'legacy',
    conversation_key: `legacy:${item.user_id}`,
  }))
  const standaloneItems = standalone.map(item => {
    let account = accountMap.get(String(item.account_id))
    if (!account) {
      const index = accounts.filter(value => value.platform === 'whatsapp').length + 1
      account = {
        id: String(item.account_id), name: item.account_name || `WhatsApp ${index}`,
        label: `WA${index}`, platform: 'whatsapp', source: 'standalone', status: 'offline',
      }
      accounts.push(account)
      accountMap.set(account.id, account)
    }
    return {
      ...item,
      platform: normalizePlatform(item.platform),
      account_label: account.label,
      source: 'standalone',
      conversation_key: `standalone:${item.conversation_id}`,
    }
  })
  const conversations = [...legacyItems, ...standaloneItems]
    .sort((a, b) => Number(b.last_timestamp || 0) - Number(a.last_timestamp || 0))

  return { accounts, conversations }
}

export function buildContacts({ legacy = [], standalone = [], accounts = [] } = {}) {
  const accountMap = new Map(accounts.map(account => [String(account.id), account]))
  const legacyAccount = accountMap.get('legacy') || { id: 'legacy', label: 'WA1', name: 'Legacy WhatsApp' }
  const legacyItems = legacy.map(item => ({
    ...item,
    contact_id: null,
    contact_key: `legacy:${item.user_id}`,
    conversation_key: `legacy:${item.user_id}`,
    account_id: 'legacy',
    account_name: legacyAccount.name,
    account_label: legacyAccount.label,
    source: 'legacy',
    platform: normalizePlatform(item.platform),
    remote_jid: item.user_id,
  }))
  const standaloneItems = standalone.map(item => {
    const account = accountMap.get(String(item.account_id)) || { label: 'WA', name: item.account_name || 'WhatsApp' }
    return {
      ...item,
      contact_key: `standalone:${item.contact_id || `${item.account_id}:${item.remote_jid || item.user_id}`}`,
      conversation_key: item.conversation_id ? `standalone:${item.conversation_id}` : '',
      account_name: item.account_name || account.name,
      account_label: account.label,
      source: 'standalone',
      platform: normalizePlatform(item.platform),
      user_id: item.user_id || item.remote_jid,
    }
  })
  return [...legacyItems, ...standaloneItems]
}

export function filterInbox(conversations, { platform = 'all', accountId = 'all' } = {}) {
  return conversations.filter(item => {
    if (platform !== 'all' && normalizePlatform(item.platform) !== normalizePlatform(platform)) return false
    if (accountId !== 'all' && String(item.account_id) !== String(accountId)) return false
    return true
  })
}
