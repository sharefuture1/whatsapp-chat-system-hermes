import test from 'node:test'
import assert from 'node:assert/strict'

import { canShortCircuitConversationFetch } from '../src/chatCache.js'

test('fresh cache only short-circuits cache-first conversation loads', () => {
  const now = 10_000
  const cached = { savedAt: now - 1_000 }

  assert.equal(canShortCircuitConversationFetch(cached, { now }), true)
  assert.equal(canShortCircuitConversationFetch(cached, { cachePolicy: 'network-first', now }), false)
  assert.equal(canShortCircuitConversationFetch(cached, { appendOlder: true, now }), false)
  assert.equal(canShortCircuitConversationFetch({ savedAt: 1 }, { now: 10 * 60 * 1000 }), false)
})
