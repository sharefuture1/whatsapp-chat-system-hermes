import test from 'node:test'
import assert from 'node:assert/strict'

import { buildContacts, buildInbox, filterInbox } from '../src/inboxModel.js'

test('buildInbox aggregates legacy and standalone WhatsApp accounts with stable WA labels', () => {
  const result = buildInbox({
    legacy: [{ user_id: 'legacy@lid', user_name: 'Legacy user', last_timestamp: 10, platform: 'whatsapp' }],
    standalone: [{ conversation_id: 'conv-2', account_id: 'account-2', account_name: 'Sales', user_id: 'new@lid', user_name: 'New user', last_timestamp: 20, platform: 'whatsapp' }],
    standaloneAccounts: [{ id: 'account-2', name: 'Sales', status: 'online' }],
  })

  assert.deepEqual(result.accounts.map(item => [item.label, item.id, item.source]), [
    ['WA1', 'legacy', 'legacy'],
    ['WA2', 'account-2', 'standalone'],
  ])
  assert.deepEqual(result.conversations.map(item => [item.conversation_key, item.account_label]), [
    ['standalone:conv-2', 'WA2'],
    ['legacy:legacy@lid', 'WA1'],
  ])
})

test('filterInbox supports ALL, platform, and platform-account scopes without losing accounts', () => {
  const inbox = buildInbox({
    legacy: [{ user_id: 'a', user_name: 'A', platform: 'whatsapp' }],
    standalone: [
      { conversation_id: 'b', account_id: 'b1', account_name: 'B1', user_id: 'b', user_name: 'B', platform: 'whatsapp' },
      { conversation_id: 'c', account_id: 'b2', account_name: 'B2', user_id: 'c', user_name: 'C', platform: 'whatsapp' },
    ],
    standaloneAccounts: [{ id: 'b1', name: 'B1' }, { id: 'b2', name: 'B2' }],
  })

  assert.equal(filterInbox(inbox.conversations, { platform: 'all', accountId: 'all' }).length, 3)
  assert.equal(filterInbox(inbox.conversations, { platform: 'whatsapp', accountId: 'all' }).length, 3)
  assert.deepEqual(
    filterInbox(inbox.conversations, { platform: 'whatsapp', accountId: 'b2' }).map(item => item.user_id),
    ['c'],
  )
})

test('buildContacts preserves identical ids from different accounts and attaches WA labels', () => {
  const contacts = buildContacts({
    legacy: [{ user_id: 'same@lid', user_name: 'Legacy Same', platform: 'whatsapp' }],
    standalone: [{ contact_id: 'c2', account_id: 'a2', remote_jid: 'same@lid', user_name: 'Second Same', platform: 'whatsapp' }],
    accounts: [
      { id: 'legacy', label: 'WA1', name: 'Legacy WhatsApp', source: 'legacy', platform: 'whatsapp' },
      { id: 'a2', label: 'WA2', name: 'Sales', source: 'standalone', platform: 'whatsapp' },
    ],
  })

  assert.deepEqual(contacts.map(item => [item.contact_key, item.account_label]), [
    ['legacy:same@lid', 'WA1'],
    ['standalone:c2', 'WA2'],
  ])
})
