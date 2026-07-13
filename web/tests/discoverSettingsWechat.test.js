import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const root = new URL('../src/', import.meta.url)
const read = path => readFileSync(new URL(path, root), 'utf8')

test('Discover page keeps only overview cards and the controlled persona library [UX-013]', () => {
  const source = read('components/DiscoverPage.jsx')
  assert.match(source, /wx-cell-group-title[^>]*>\s*\{t\('personaLibrary'\)\}/)
  assert.match(source, /t\('overview'\)/)
  assert.doesNotMatch(source, /wx-plugin-filters/)
  assert.doesNotMatch(source, /pluginCenter/)
  assert.doesNotMatch(source, /\bToolsPanel\b/)
})

test('Settings panel no longer exposes schedule or broadcast forms [UX-013]', () => {
  const source = read('components/SettingsPanel.jsx')
  assert.doesNotMatch(source, /<ToolsPanel\s*\/>/)
  assert.doesNotMatch(source, /tab === 'tools'/)
  assert.doesNotMatch(source, /tab === 'broadcast'/)
  assert.doesNotMatch(source, /addSchedule|sendBroadcast|loadAll\(\{/)
  assert.match(source, /t\('globalAi'\)/)
  assert.match(source, /t\('security'\)/)
})

test('Me page exposes a Plugins entry that opens the plugin center [UX-013]', () => {
  const source = read('components/MePage.jsx')
  assert.match(source, /onOpenPlugins/)
  assert.match(source, /t\('pluginCenter'\)/)
})
