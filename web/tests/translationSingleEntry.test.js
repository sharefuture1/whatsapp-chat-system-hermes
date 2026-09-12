import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const source = readFileSync(new URL('../src/components/ChatPane.jsx', import.meta.url), 'utf8')

test('FR-AI-015: standalone page never auto-creates translation batches', () => {
  assert.doesNotMatch(source, /const queueTranslationBatch\s*=/)
  assert.doesNotMatch(source, /await api\.post\(`\/v1\/conversations\/\$\{encodeURIComponent\(conversationId\)\}\/translations`/)
  assert.match(source, /if \(standalone \|\| !autoTranslate \|\| !userId \|\| translationWorkerRunningRef\.current\) return/)
})

test('FR-AI-015: legacy automatic translation keeps the per-message worker path', () => {
  assert.match(source, /await translateOne\(msg, generation, controller\.signal\)/)
})


test('FR-AI-015: non-admin capabilities feed the same effective auto-translate state', () => {
  const app = readFileSync(new URL('../src/App.jsx', import.meta.url), 'utf8')
  assert.match(app, /auto_translate: data\.auto_translate \|\| \{\}/)
  assert.match(app, /setApiSettings\(isAdmin \? aiData : \{ auto_translate: settingsData\.auto_translate \|\| \{\} \}\)/)
})
