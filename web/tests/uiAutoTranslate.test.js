import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'

const src = path.resolve('src')
const read = file => fs.readFileSync(path.join(src, file), 'utf8')

test('auto translate uses one effective gate including plugin and AI availability', () => {
  const app = read('App.jsx')
  assert.match(app, /deriveAutoTranslateState/)
  assert.match(app, /aiConfigured/)
  assert.match(app, /pluginEnabled/)
  assert.match(app, /<ChatPane[\s\S]*autoTranslate=/)
})

test('ChatPane surfaces translation failures instead of swallowing them', () => {
  const pane = read('components/ChatPane.jsx')
  assert.match(pane, /translationError/)
  assert.doesNotMatch(pane, /const translateOne[\s\S]*?catch \{\}/)
  assert.match(pane, /autoTranslate = false/)
})

test('page styling defines every account page class and desktop content constraints', () => {
  const css = read('styles.css')
  for (const className of [
    'wx-account-page', 'wx-account-list', 'wx-account-row', 'wx-account-qr-box',
    'wx-account-detail-hero', 'wx-account-danger-zone', 'wx-section-list',
    'wx-setting-row-icon', 'wx-page-header', 'wx-skeleton-msg-list',
  ]) assert.match(css, new RegExp(`\\.${className}\\b`), className)
  assert.match(css, /@media \(min-width: 900px\)[\s\S]*\.wx-page[^}]*max-width/)
  assert.match(css, /--wx-border:/)
  assert.match(css, /--wx-radius-md:/)
  assert.match(css, /--wx-text-secondary:/)
})
