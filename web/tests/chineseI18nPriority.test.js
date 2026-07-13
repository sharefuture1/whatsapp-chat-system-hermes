import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'

const root = new URL('../src/', import.meta.url)
const read = file => fs.readFileSync(new URL(file, root), 'utf8')

test('Chinese is the default and highest-priority i18n fallback [UX-011]', () => {
  const i18n = read('i18n.js')
  const settings = read('settings.jsx')
  assert.match(i18n, /\{ code: 'zh', label: '中文' \}/)
  assert.match(i18n, /const dict = STRINGS\[language\] \?\? STRINGS\.zh/)
  assert.match(i18n, /return dict\[key\] \?\? STRINGS\.zh\[key\] \?\? key/)
  assert.match(i18n, /if \(typeof navigator === 'undefined'\) return 'zh'/)
  assert.match(i18n, /return 'zh'/)
  assert.match(settings, /const LANG_KEY = 'chat-system-language-v2'/)
  assert.match(settings, /readStored\(LANG_KEY, 'zh'\)/)
  assert.match(settings, /setLanguageState\(SUPPORTED_LANGUAGES\.some\(l => l\.code === lang\) \? lang : 'zh'\)/)
  assert.match(settings, /language: 'zh'/)
  assert.match(settings, /translate\('zh', key\)/)
})
