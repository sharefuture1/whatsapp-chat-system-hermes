import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const read = path => readFileSync(new URL(`../src/${path}`, import.meta.url), 'utf8')

test('mobile chats use explicit list and conversation states with a working back action', () => {
  const app = read('App.jsx')
  const css = read('styles.css')
  assert.match(app, /mobile-chat-open.*mobile-list-open/)
  assert.match(app, /onBack=\{\(\) => \{ setSelectedId\(''\)/)
  assert.match(app, /hidden=\{\(activeTab === 'chats' && Boolean\(selectedId\)\)/)
  assert.match(css, /mobile-list-open \.wx-sidebar \{ display: flex/)
  assert.match(css, /mobile-list-open \.wx-chat \{ display: none/)
  assert.match(css, /mobile-chat-open \.wx-sidebar \{ display: none/)
  assert.match(css, /mobile-chat-open \.wx-chat \{ display: flex/)
})

test('workspace refresh does not auto-select the first conversation', () => {
  const source = read('App.jsx')
  assert.doesNotMatch(source, /if \(!prev\)[\s\S]{0,160}items\[0\]/)
})

test('temporary pending and failed messages are never submitted for translation', () => {
  const source = read('components/ChatPane.jsx')
  assert.match(source, /translationId\.startsWith\('tmp-'\)/)
  assert.match(source, /msg\.pending/)
  assert.match(source, /msg\.failed/)
  assert.match(source, /messages\.filter\([\s\S]*!String\(m\.message_id[\s\S]*startsWith\('tmp-'\)/)
})

test('successful send replaces optimistic id with a real server id', () => {
  const source = read('components/ChatPane.jsx')
  assert.match(source, /const finalId = data\?\.local_message_id \|\| data\?\.message_id/)
  assert.match(source, /message_id: finalId/)
})

test('pinned conversations are excluded from the normal list and unread is a dot', () => {
  const source = read('components/ChatList.jsx')
  assert.match(source, /const normalItems = conversations\.filter/)
  assert.match(source, /normalItems\.map\(renderRow\)/)
  assert.match(source, /wx-unread-dot/)
  assert.doesNotMatch(source, /wx-unread-badge[^\n]*99\+/)
})

test('fresh server messages preserve local sent state when role and content match', () => {
  const source = read('chatSync.js')
  assert.match(source, /sentByContent/)
  assert.match(source, /sent: true/)
})

test('bubble timestamps use HH:MM and collapse same-sender messages within five minutes', () => {
  const source = read('components/ChatPane.jsx')
  const format = read('format.js')
  assert.match(source, /delta > 300/)
  assert.match(source, /fmtClock\(item\.timestamp\)/)
  assert.match(format, /hour: '2-digit', minute: '2-digit'/)
})

test('translation hides identical text and hide control is interaction-only', () => {
  const source = read('components/ChatPane.jsx')
  const css = read('styles.css')
  assert.match(source, /translatedText !== contentText/)
  assert.match(css, /\.wx-translation-hide \{ opacity: 0; pointer-events: none/)
  assert.match(css, /\.wx-bubble-row:hover \.wx-translation-hide, \.wx-bubble-row\.is-active \.wx-translation-hide/)
})

test('composer measures scrollHeight and exposes three direct mode choices', () => {
  const source = read('components/ChatPane.jsx')
  assert.match(source, /onInput=\{resizeComposer\}/)
  assert.match(source, /scrollHeight/)
  assert.match(source, /setMode\('direct'\)/)
  assert.match(source, /setMode\('smart'\)/)
  assert.match(source, /setMode\('translate'\)/)
})

test('settings modal becomes a full screen page on mobile', () => {
  const css = read('styles.css')
  assert.match(css, /@media \(max-width: 760px\)[\s\S]*\.modal-backdrop \{[^}]*padding: 0/)
  assert.match(css, /@media \(max-width: 760px\)[\s\S]*\.modal \{[^}]*width: 100vw[^}]*height: 100dvh[^}]*border-radius: 0/)
})

test('operator avatar is language independent', () => {
  const source = read('components/MePage.jsx')
  assert.doesNotMatch(source, /t\('operatorInitial'\)/)
  assert.match(source, /svg viewBox/)
})
