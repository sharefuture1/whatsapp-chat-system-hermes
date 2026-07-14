import assert from 'node:assert/strict'
import fs from 'node:fs'
import test from 'node:test'

import { contactSelectionPlan, conversationDeletePlan } from '../src/conversationLifecycle.js'

const appSource = fs.readFileSync(new URL('../src/App.jsx', import.meta.url), 'utf8')
const contactsSource = fs.readFileSync(new URL('../src/components/ContactsPage.jsx', import.meta.url), 'utf8')

test('legacy hidden contact restores then selects its conversation key', () => {
  assert.deepEqual(contactSelectionPlan({
    source: 'legacy', user_id: 'person@lid', conversation_deleted: true,
    conversation_key: 'legacy:person@lid',
  }), {
    ensure: { method: 'POST', path: '/chat/restore', body: { user_id: 'person@lid' } },
    conversationKey: 'legacy:person@lid',
  })
})

test('standalone contact without conversation ensures a scoped conversation', () => {
  assert.deepEqual(contactSelectionPlan({ source: 'standalone', contact_id: 'contact-1' }), {
    ensure: { method: 'POST', path: '/v1/contacts/contact-1/conversation', body: {} },
    conversationKey: '',
  })
})

test('delete plans use source-specific endpoint and conversation key identity', () => {
  assert.deepEqual(conversationDeletePlan({ source: 'legacy', user_id: 'person@lid', conversation_key: 'legacy:person@lid' }), {
    method: 'POST', path: '/chat/delete', body: { user_id: 'person@lid' }, conversationKey: 'legacy:person@lid', pinKey: 'person@lid',
  })
  assert.deepEqual(conversationDeletePlan({ source: 'standalone', conversation_id: 'conv-1', user_id: 'person@lid', conversation_key: 'standalone:conv-1' }), {
    method: 'DELETE', path: '/v1/conversations/conv-1', body: undefined, conversationKey: 'standalone:conv-1', pinKey: 'person@lid',
  })
})

test('App loads V1 as primary while keeping legacy contacts as migration fallback', () => {
  assert.match(appSource, /api\.get\(`\/v1\/conversations\?platform=all/)
  assert.match(appSource, /api\.get\('\/contacts\?page=/)
  assert.match(appSource, /legacy:\s*legacyContactsRes\.items/)
  assert.doesNotMatch(contactsSource, /disabled=\{!item\.conversation_key\}/)
})
