import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'

const file = new URL('../src/i18n.js', import.meta.url)

function localeBlock(source, locale) {
  const start = source.indexOf(`  ${locale}: {`)
  assert.notEqual(start, -1, `missing ${locale} locale`)
  const next = ['en', 'zh', 'th', 'lo']
    .filter(item => item !== locale)
    .map(item => source.indexOf(`  ${item}: {`, start + 1))
    .filter(index => index !== -1)
  const end = next.length ? Math.min(...next) : source.indexOf('\n  },\n}', start)
  return source.slice(start, end)
}

test('Chinese locale has no untranslated English UI values [UX-011]', () => {
  const zh = localeBlock(fs.readFileSync(file, 'utf8'), 'zh')
  const values = [...zh.matchAll(/^    [A-Za-z][A-Za-z0-9_]*: '([^']*)'/gm)].map(match => match[1])
  const untranslated = values.filter(value => {
    const terms = value.replace(/\{[^}]+\}/g, '').match(/[A-Za-z]{4,}/g) || []
    return terms.some(term => !['WhatsApp', 'Hermes', 'Worker', 'Bridge'].includes(term))
  })
  assert.deepEqual(untranslated, [])
})
