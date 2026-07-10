import test from 'node:test'
import assert from 'node:assert/strict'

import { createConversationRequestTracker } from '../src/chatSync.js'

test('only the latest request for the active conversation may update state', () => {
  const tracker = createConversationRequestTracker()
  tracker.activate('contact-a')
  const requestA = tracker.begin('contact-a')
  tracker.activate('contact-b')
  const requestB = tracker.begin('contact-b')

  assert.equal(tracker.isCurrent(requestA, 'contact-a'), false)
  assert.equal(tracker.isCurrent(requestB, 'contact-b'), true)
})

test('a late request for an inactive conversation cannot become current', () => {
  const tracker = createConversationRequestTracker()
  tracker.activate('contact-b')

  const lateRequestA = tracker.begin('contact-a')

  assert.equal(tracker.isCurrent(lateRequestA, 'contact-a'), false)
})

test('the active conversation remains identifiable after a request fails', () => {
  const tracker = createConversationRequestTracker()
  tracker.activate('contact-a')
  tracker.begin('contact-a')

  assert.equal(tracker.isActive('contact-a'), true)
  assert.equal(tracker.isActive('contact-b'), false)
})

test('invalidating the tracker rejects an in-flight response', () => {
  const tracker = createConversationRequestTracker()
  tracker.activate('contact-a')
  const request = tracker.begin('contact-a')

  tracker.invalidate()

  assert.equal(tracker.isCurrent(request, 'contact-a'), false)
})
