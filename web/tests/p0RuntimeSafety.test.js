import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const root = new URL('../src/', import.meta.url)
const read = path => readFileSync(new URL(path, root), 'utf8')

test('selected chat status comes from an explicit prop instead of an undeclared variable', () => {
  const app = read('App.jsx')
  const chatPane = read('components/ChatPane.jsx')

  assert.match(app, /accountStatus=\{selectedConversationAccount\?\.status \|\| 'offline'\}/)
  assert.match(chatPane, /accountStatus = 'offline'/)
  assert.doesNotMatch(chatPane, /\bactiveAccount\b/)
})

test('settings pages import every React hook and never call hooks after an early return', () => {
  const settingsPage = read('components/SettingsPage.jsx')
  const settingsPanel = read('components/SettingsPanel.jsx')

  assert.match(settingsPage, /import \{ useEffect, useState \} from 'react'/)
  assert.match(settingsPanel, /import \{ useEffect, useMemo, useState \} from 'react'/)
  assert.ok(settingsPanel.indexOf('const contactsForPicker = useMemo') < settingsPanel.indexOf('if (!open) return null'))
})

test('manual, polling, and translation refreshes bypass fresh local conversation cache', () => {
  const chatPane = read('components/ChatPane.jsx')
  const networkFirstCalls = chatPane.match(/cachePolicy: 'network-first'/g) || []

  assert.ok(networkFirstCalls.length >= 3)
  assert.match(chatPane, /canShortCircuitConversationFetch\(cached, \{ appendOlder, cachePolicy \}\)/)
})

test('missing Standalone refresh setting gets a reliable default while explicit zero remains supported', () => {
  const app = read('App.jsx')

  assert.match(app, /configuredAutoSeconds == null \? 30/)
  assert.match(app, /autoSeconds > 0 \? Math\.max\(30, autoSeconds\) : 0/)
})
