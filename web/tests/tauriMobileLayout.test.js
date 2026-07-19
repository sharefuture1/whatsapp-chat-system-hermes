import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const webRoot = new URL('../', import.meta.url)
const read = path => readFileSync(new URL(path, webRoot), 'utf8')

test('Tauri mobile viewport follows the visual keyboard viewport with dvh fallback', () => {
  const index = read('index.html')
  const main = read('src/main.jsx')
  const css = read('src/styles.css')

  assert.match(index, /viewport-fit=cover/)
  assert.match(index, /interactive-widget=resizes-content/)
  assert.match(main, /installViewportHeightSync\(\)/)
  assert.match(css, /--app-viewport-height:\s*100vh/)
  assert.match(css, /@supports \(height: 100dvh\)[\s\S]*--app-viewport-height:\s*100dvh/)
  assert.match(css, /\.wx-shell \{[^}]*height:\s*var\(--app-viewport-height\)/)
  assert.match(css, /\.wx-auth-shell \{[^}]*height:\s*var\(--app-viewport-height\)[^}]*overflow:\s*hidden/)
  assert.match(css, /\.modal \{[^}]*height:\s*var\(--app-viewport-height\)[^}]*max-height:\s*var\(--app-viewport-height\)/)
})

test('mobile navigation and fixed surfaces preserve notch and home-indicator safe areas', () => {
  const css = read('src/styles.css')
  const accountCss = read('src/account-center.css')

  assert.match(css, /@media \(max-width: 760px\)[\s\S]*\.wx-sidebar-header \{[\s\S]*safe-area-inset-top/)
  assert.match(css, /@media \(max-width: 760px\)[\s\S]*\.wx-chat-header \{[\s\S]*safe-area-inset-top/)
  assert.match(css, /@media \(max-width: 760px\)[\s\S]*\.wx-tab-bar \{[\s\S]*safe-area-inset-bottom/)
  assert.match(css, /\.wx-chat-layout\.mobile-list-open \.wx-sidebar \{ display: flex/)
  assert.match(css, /\.wx-chat-layout\.mobile-chat-open \.wx-chat \{ display: flex/)
  assert.match(accountCss, /\.wx-account-page-header\{[^}]*safe-area-inset-top[^}]*safe-area-inset-left/)
  assert.match(accountCss, /\.wx-account-add-bar\{[^}]*safe-area-inset-bottom[^}]*safe-area-inset-left/)
})

test('core flex surfaces may shrink instead of forcing a desktop width on phones', () => {
  const css = read('src/styles.css')
  const accountCss = read('src/account-center.css')

  assert.match(css, /\.wx-shell-content \{[^}]*width:\s*100%[^}]*min-width:\s*0/)
  assert.match(css, /\.wx-chat-layout \{[^}]*width:\s*100%[^}]*min-width:\s*0/)
  assert.match(css, /\.wx-page \{[^}]*width:\s*100%[^}]*min-width:\s*0/)
  assert.match(accountCss, /width:min\(760px,100%\)/)
})
