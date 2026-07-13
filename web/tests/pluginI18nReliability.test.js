import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'

const root = new URL('../src/', import.meta.url)
const read = file => fs.readFileSync(new URL(file, root), 'utf8')

function readLocaleKeys(source, locale) {
  const start = source.indexOf(`  ${locale}: {`)
  assert.notEqual(start, -1, `missing ${locale} locale`)
  const pos = start + `  ${locale}: {`.length
  let depth = 1
  let i = pos
  while (i < source.length && depth > 0) {
    const ch = source[i]
    if (ch === '{') depth += 1
    else if (ch === '}') depth -= 1
    i += 1
  }
  const block = source.slice(pos, i - 1)
  return [...block.matchAll(/^    ([A-Za-z][A-Za-z0-9_]*):/gm)].map(match => match[1])
}

test('all four locales expose an identical, duplicate-free key set [SDD-P1-06]', () => {
  const source = read('i18n.js')
  const expected = readLocaleKeys(source, 'en').sort()
  assert.ok(expected.length > 200)
  for (const locale of ['en', 'zh', 'th', 'lo']) {
    const keys = readLocaleKeys(source, locale)
    assert.equal(new Set(keys).size, keys.length, `${locale} contains duplicate keys`)
    assert.deepEqual(keys.slice().sort(), expected, `${locale} key set differs from English`)
  }
})

test('translation fallback does not discard an intentional empty/missing locale value', () => {
  const source = read('i18n.js')
  assert.match(source, /return dict\[key\] \?\? STRINGS\.zh\[key\] \?\? key/)
})

test('plugin centers expose operational state and never offer unavailable plugins as actions', () => {
  for (const file of ['components/PluginCenterPage.jsx']) {
    const source = read(file)
    assert.match(source, /plugin\.available === false/)
    assert.match(source, /disabled=\{plugin\.available === false/)
    assert.match(source, /pluginUnavailable/)
  }
  const pluginCenter = read('components/PluginCenterPage.jsx')
  assert.match(pluginCenter, /setRefreshing\(true\)/)
  assert.match(pluginCenter, /!loading && !error && filtered\.length === 0/)
})
