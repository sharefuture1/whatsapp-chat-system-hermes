import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const root = new URL('../src/', import.meta.url)
const read = path => readFileSync(new URL(path, root), 'utf8')

test('PluginCenter page surfaces real availability and reasons [UX-013]', () => {
  const source = read('components/PluginCenterPage.jsx')
  assert.match(source, /plugin\.available === false/)
  assert.match(source, /plugin\.status_when_on/)
  assert.match(source, /plugin\.unavailable_reason/)
  assert.match(source, /pluginUnavailableReason/)
  assert.match(source, /setRefreshing\(true\)/)
  assert.match(source, /api\.post\('\/v1\/plugins\/toggle'/)
  assert.match(source, /api\.delete\(`\/v1\/plugins\/\$\{plugin\.id\}`/)
})

test('SchedulerCenter and BroadcastCenter pages exist and reuse the API client', () => {
  const schedule = read('components/SchedulerCenterPage.jsx')
  const broadcast = read('components/BroadcastCenterPage.jsx')
  for (const src of [schedule, broadcast]) {
    assert.match(src, /useEffect/)
    assert.match(src, /api\.get\(/)
    assert.match(src, /useSettings/)
    assert.match(src, /onBack/)
  }
  assert.match(schedule, /run_at|runAt/)
  assert.match(broadcast, /targets/)
})

test('i18n exposes scheduler and broadcast state keys', () => {
  const source = read('i18n.js')
  for (const key of ['schedulerTitle', 'broadcastTitle', 'pluginUnavailableReason']) {
    assert.match(source, new RegExp(`${key}\\s*:`))
  }
})
