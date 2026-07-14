import assert from 'node:assert/strict'
import test from 'node:test'
import { formatChatDay, localDayKey } from '../src/dateTime.js'

test('localDayKey respects Asia/Vientiane midnight instead of UTC', () => {
  const timestamp = Date.parse('2026-07-12T18:30:00Z') / 1000
  assert.equal(localDayKey(timestamp, 'Asia/Vientiane'), '2026-07-13')
  assert.equal(localDayKey(timestamp, 'UTC'), '2026-07-12')
})

test('formatChatDay resolves today and yesterday in the requested timezone', () => {
  const t = key => key
  const now = new Date('2026-07-13T12:00:00Z')
  assert.equal(formatChatDay(Date.parse('2026-07-13T01:00:00Z') / 1000, t, now, 'Asia/Vientiane'), 'today')
  assert.equal(formatChatDay(Date.parse('2026-07-12T01:00:00Z') / 1000, t, now, 'Asia/Vientiane'), 'yesterday')
})
