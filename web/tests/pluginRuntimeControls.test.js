import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

import { mergeFreshMessages } from '../src/chatSync.js'

const root = new URL('../src/', import.meta.url)
const read = path => readFileSync(new URL(path, root), 'utf8')

test('plugin toggle notifies the app so effective capabilities update immediately', () => {
  const app = read('App.jsx')
  const center = read('components/PluginCenterPage.jsx')

  assert.match(app, /onPluginsChanged=/)
  assert.match(center, /onPluginsChanged/)
  assert.match(center, /onPluginsChanged\?\.\(\)/)
})

test('reply request carries the selected mode to the backend', () => {
  const app = read('App.jsx')
  assert.match(app, /message,\s*mode,\s*idempotency_key:\s*idempotencyKey/)
})

test('chat renders day separators as separators instead of empty message bubbles', () => {
  const pane = read('components/ChatPane.jsx')
  assert.match(pane, /item\.type === 'day'/)
  assert.match(pane, /wx-day/)
})

test('one server confirmation consumes only one identical optimistic message', () => {
  const current = [
    { message_id: 'tmp-1', role: 'assistant', content: '好的', pending: true, local_only: true, timestamp: 1 },
    { message_id: 'tmp-2', role: 'assistant', content: '好的', pending: true, local_only: true, timestamp: 2 },
  ]
  const server = [
    { message_id: 'srv-1', platform_message_id: 'wa-1', role: 'assistant', content: '好的', status: 'sent', timestamp: 1 },
  ]

  const merged = mergeFreshMessages(server, current)
  assert.equal(merged.length, 2)
  assert.equal(merged.filter(item => String(item.message_id).startsWith('tmp-')).length, 1)
})

test('an old identical server message cannot consume a new optimistic message', () => {
  const current = [
    { message_id: 'srv-old', platform_message_id: 'wa-old', role: 'assistant', content: '好的', status: 'sent', sent: true, timestamp: 1 },
    { message_id: 'tmp-new', role: 'assistant', content: '好的', pending: true, local_only: true, timestamp: 100 },
  ]
  const server = [
    { message_id: 'srv-old', platform_message_id: 'wa-old', role: 'assistant', content: '好的', status: 'sent', sent: true, timestamp: 1 },
  ]

  const merged = mergeFreshMessages(server, current)
  assert.equal(merged.length, 2)
  assert.ok(merged.some(item => item.message_id === 'tmp-new'))
})
