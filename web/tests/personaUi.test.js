import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'

const root = new URL('../src/', import.meta.url)
const read = file => fs.readFileSync(new URL(file, root), 'utf8')

function readLocaleKeys(source, locale) {
  const start = source.indexOf(`  ${locale}: {`)
  assert.notEqual(start, -1, `missing ${locale} locale`)
  const next = ['en', 'zh', 'th', 'lo']
    .filter(item => item !== locale)
    .map(item => source.indexOf(`  ${item}: {`, start + 1))
    .filter(index => index !== -1)
  const end = next.length ? Math.min(...next) : source.indexOf('\n  },\n}', start)
  return [...source.slice(start, end).matchAll(/^    ([A-Za-z][A-Za-z0-9_]*):/gm)].map(match => match[1])
}

test('Persona catalog stays API-backed via the chat picker; Discover no longer embeds it [FR-PLG-007 / SDD-P1-11]', () => {
  const module = read('personas.js')
  assert.match(module, /fetchPersonaCatalog/)
  assert.match(module, /\/v1\/personas/)
  // SDD-P1-11：Discover 仅保留运营概览，人设目录迁移到聊天页头部 picker
  const discover = read('components/DiscoverPage.jsx')
  assert.doesNotMatch(discover, /fetchPersonaCatalog/)
  const chatPane = read('components/ChatPane.jsx')
  assert.match(chatPane, /fetchPersonaCatalog/)
})

test('Chat persona picker assigns only the active contact and shows preview persona [FR-PLG-008]', () => {
  const chatPane = read('components/ChatPane.jsx')
  const module = read('personas.js')
  assert.match(module, /assignPersona/)
  assert.match(chatPane, /from '\.\.\/personas'/)
  assert.match(chatPane, /fetchPersonaCatalog/)
  assert.match(chatPane, /assignPersonaApi/)
  assert.match(chatPane, /wx-persona-picker/)
  assert.match(chatPane, /wx-current-persona/)
  assert.match(chatPane, /preview\?\.persona/)
  assert.match(chatPane, /personaPicker/)
})

test('smart and translate preview uses the reply contract without sending [FR-PLG-008]', () => {
  const chatPane = read('components/ChatPane.jsx')
  const app = read('App.jsx')
  assert.match(chatPane, /const previewReply = async \(\) => \{/)
  assert.match(chatPane, /onReply\(userId, text, previewMode, \{ previewOnly: true \}\)/)
  assert.match(chatPane, /previewMode === 'direct'/)
  assert.match(chatPane, /data\?\.rewrite \? \{/)
  assert.match(chatPane, /setPreview\(null\)/)
  assert.match(chatPane, /onClick=\{previewReply\}/)
  assert.match(app, /const sendReply = async \(conversation, message, mode, \{ previewOnly = false, idempotencyKey = null \} = \{\}\) => \{/)
  assert.match(app, /preview_only:\s*previewOnly/)
  assert.match(app, /idempotency_key:\s*idempotencyKey/)
  assert.match(app, /\(target, message, mode, options\) => sendReply\(selectedConversation, message, mode, options\)/)
})

test('persona UI copy is localized in all supported locales [UX-007]', () => {
  const source = read('i18n.js')
  for (const locale of ['en', 'zh', 'th', 'lo']) {
    const keys = new Set(readLocaleKeys(source, locale))
    for (const key of ['personaLibrary', 'personaAvailable', 'personaUnavailable', 'personaPicker', 'personaDefault', 'personaCurrent', 'personaUse', 'personaLoading', 'personaLoadFailed']) {
      assert.ok(keys.has(key), `${locale} missing ${key}`)
    }
  }
})
