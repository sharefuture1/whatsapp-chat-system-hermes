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

test('all conversation refreshes revalidate fresh local cache against the server [PERF-008]', () => {
  const chatPane = read('components/ChatPane.jsx')

  assert.doesNotMatch(chatPane, /canShortCircuitConversationFetch/)
  assert.match(chatPane, /本地缓存只作首屏骨架/)
})

test('Tauri mode keeps the session token out of localStorage and logout clears chat caches', () => {
  const app = read('App.jsx')
  const cache = read('chatCache.js')

  assert.match(app, /isTauri\(\) \? '' : localStorage\.getItem\(TOKEN_KEY\)/)
  assert.match(app, /if \(!isTauri\(\)\) localStorage\.setItem\(TOKEN_KEY, data\.session_token\)/)
  assert.match(app, /clearAllChatCaches\(\)/)
  assert.match(cache, /export function clearAllChatCaches\(\)/)
})

test('missing, invalid, and zero refresh settings use the PERF-001 five-second default', () => {
  const app = read('App.jsx')

  assert.match(app, /Math\.min\(300, Math\.max\(3, autoSeconds\)\)/)
  assert.match(app, /: 5\b/)
  assert.doesNotMatch(app, /Math\.max\(30/)
})
