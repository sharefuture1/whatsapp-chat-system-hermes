import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const read = path => readFileSync(new URL(`../src/${path}`, import.meta.url), 'utf8')

test('account polling keeps the accounts array stable when server data is unchanged', () => {
  const source = read('accounts/useAccountsController.js')
  assert.match(source, /sameAccounts/)
  assert.match(source, /setAccounts\(prev => sameAccounts\(prev, next\) \? prev : next\)/)
})

test('workspace refresh callback is not recreated by every account poll', () => {
  const source = read('App.jsx')
  assert.doesNotMatch(source, /fetchConversationsPage[\s\S]*?\}, \[accountsController\.accounts\]\)/)
})

test('chat initial load depends on stable conversation identity instead of the full ui settings object', () => {
  const source = read('components/ChatPane.jsx')
  assert.match(source, /const defaultMode = uiSettings\?\.reply\?\.default_mode \|\| 'smart'/)
  assert.match(source, /\[conversationKey, defaultMode, pageSize\]/)
  assert.doesNotMatch(source, /\[userId, conversationId, standalone, pageSize, uiSettings\]/)
})

test('WeChat chat header exposes a single overflow action and composer tools are collapsible', () => {
  const source = read('components/ChatPane.jsx')
  assert.match(source, /wx-chat-more-btn/)
  assert.match(source, /setToolsOpen/)
  assert.match(source, /wx-composer-tools-panel/)
  assert.doesNotMatch(source, /wx-chat-header-right[\s\S]*contactProfile[\s\S]*chatHistory/)
})

test('auto translation tracks in-flight message ids to prevent duplicate provider calls', () => {
  const source = read('components/ChatPane.jsx')
  assert.match(source, /translatingIdsRef/)
  assert.match(source, /translatingIdsRef\.current\.has/)
  assert.match(source, /translatingIdsRef\.current\.add/)
  assert.match(source, /translatingIdsRef\.current\.delete/)
})

test('WeChat translation is rendered inside the owning message bubble', () => {
  const source = read('components/ChatPane.jsx')
  assert.match(source, /wx-bubble-translation/)
  assert.doesNotMatch(source, /<div className="wx-translation-line">/)
})

test('WeChat bubble rows render square avatars for both incoming and outgoing messages', () => {
  const source = read('components/ChatPane.jsx')
  assert.match(source, /isOut \? 'operatorAvatar' : userName/)
  assert.match(source, /initials\(isOut \?/)
})
