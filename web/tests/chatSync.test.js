import test from 'node:test'
import assert from 'node:assert/strict'

import {
  commitMessagesUpdate,
  createConversationDeltaScheduler,
  createConversationRequestTracker,
  mergeFreshMessages,
  mergeNewMessages,
  mergeNewMessagesWithStats,
  isTranslationRetryEligible,
  nextTranslationRetryDelay,
} from '../src/chatSync.js'

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

test('server refresh preserves sent state by matching role and content', () => {
  const current = [{ message_id: '42', role: 'assistant', content: 'hello', sent: true }]
  const server = [{ message_id: '43', role: 'assistant', content: 'hello' }]
  assert.deepEqual(mergeFreshMessages(server, current), [{ message_id: '43', role: 'assistant', content: 'hello', sent: true }])
})

test('pending local bubbles remain until matching server content arrives', () => {
  const current = [{ message_id: 'tmp-1', role: 'assistant', content: 'hello', pending: true }]
  assert.equal(mergeFreshMessages([], current).length, 1)
  assert.equal(mergeFreshMessages([{ message_id: '5', role: 'assistant', content: 'hello' }], current).length, 1)
})

test('delta merge upserts server fields for the same message id while preserving local optimistic state', () => {
  const current = [{
    message_id: '42', content: 'draft', role: 'assistant', timestamp: 10,
    pending: true, sent: true, translated: 'old', lang: 'Unknown', translationError: 'retry',
  }]
  const incoming = [{
    message_id: '42', content: 'final', timestamp: 10, translated: '你好', lang: 'English',
    status: 'delivered', platform_message_id: 'wa-42',
  }]
  assert.deepEqual(mergeNewMessages(current, incoming), [{
    message_id: '42', content: 'final', role: 'assistant', timestamp: 10,
    pending: false, sent: true, translated: '你好', lang: 'English', translationError: 'retry',
    status: 'delivered', platform_message_id: 'wa-42', local_only: false, failed: false,
  }])
})

test('delta merge appends new messages in stable chronological order', () => {
  const first = { message_id: '10', content: 'first', timestamp: 20 }
  const sameTimeA = { message_id: 'uuid-a', content: 'a', timestamp: 30 }
  const sameTimeB = { message_id: 'uuid-b', content: 'b', timestamp: 30 }
  assert.deepEqual(mergeNewMessages([sameTimeA], [sameTimeB, first]).map(item => item.message_id), ['10', 'uuid-a', 'uuid-b'])
})

test('fresh refresh preserves local translation fields when the server omits them', () => {
  const current = [{ message_id: '42', role: 'user', content: 'hello', translated: '你好', lang: 'English', translationError: 'cached warning' }]
  const server = [{ message_id: '42', role: 'user', content: 'hello' }]
  assert.deepEqual(mergeFreshMessages(server, current), [current[0]])
})

test('fresh refresh overwrites local translation fields when the server provides them', () => {
  const current = [{ message_id: '42', role: 'user', content: 'hello', translated: '旧', lang: 'Unknown', translationError: 'old' }]
  const server = [{ message_id: '42', role: 'user', content: 'hello', translated: '新', lang: 'English', translationError: '' }]
  assert.deepEqual(mergeFreshMessages(server, current), [server[0]])
})

test('fresh V2 Unknown without translated keeps all local translation metadata', () => {
  const current = [{ message_id: 'v2-42', content: 'hello', translated: '你好', lang: 'English', translationError: 'retry later' }]
  const server = [{ message_id: 'v2-42', content: 'hello', lang: 'Unknown' }]
  assert.deepEqual(mergeFreshMessages(server, current), [current[0]])
})

test('fresh refresh treats either a real translation or a real language as valid server metadata', () => {
  const current = [{ message_id: '42', content: 'hello', translated: '旧', lang: 'English', translationError: 'old' }]
  assert.deepEqual(mergeFreshMessages([{ message_id: '42', content: 'hello', translated: '新' }], current), [
    { message_id: '42', content: 'hello', translated: '新' },
  ])
  assert.deepEqual(mergeFreshMessages([{ message_id: '42', content: 'hello', lang: 'Spanish' }], current), [
    { message_id: '42', content: 'hello', lang: 'Spanish' },
  ])
})

test('delta server delivery reconciles optimistic flags instead of preserving pending', () => {
  const optimistic = [{ message_id: '42', content: 'hello', pending: true, local_only: true, failed: true }]
  assert.deepEqual(mergeNewMessages(optimistic, [{ message_id: '42', status: 'delivered', platform_message_id: 'wa-42' }]), [
    { message_id: '42', content: 'hello', pending: false, local_only: false, failed: false, status: 'delivered', platform_message_id: 'wa-42' },
  ])
  assert.deepEqual(mergeNewMessages(optimistic, [{ message_id: '42', status: 'failed' }]), [
    { message_id: '42', content: 'hello', pending: false, local_only: false, failed: true, status: 'failed' },
  ])
})

test('delta merge stats count only unique newly inserted ids', () => {
  assert.equal(mergeNewMessagesWithStats([], [{ message_id: '1' }]).newCount, 1)
  assert.equal(mergeNewMessagesWithStats([{ message_id: '1', content: 'old' }], [{ message_id: '1', content: 'new' }]).newCount, 0)
  assert.equal(mergeNewMessagesWithStats([], [{ message_id: '1' }, { message_id: '1', status: 'read' }]).newCount, 1)
})

test('translation retry helpers impose a future retry boundary and bounded wakeup', () => {
  const now = 1_000
  assert.equal(isTranslationRetryEligible({ translationRetryAfter: now + 30_000 }, now), false)
  assert.equal(isTranslationRetryEligible({ translationRetryAfter: now }, now), true)
  assert.equal(nextTranslationRetryDelay([{ translationRetryAfter: now + 30_000 }, { translationRetryAfter: now + 5_000 }], now), 5_000)
  assert.equal(nextTranslationRetryDelay([{ translationRetryAfter: now - 1 }], now), 0)
})

test('translation failure synchronously updates the worker ref before follow-up selection', () => {
  const now = 1_000
  const messagesRef = { current: [{ message_id: '42', content: 'hello', lang: 'English' }] }
  let renderedMessages = messagesRef.current

  commitMessagesUpdate(messagesRef, next => { renderedMessages = next }, previous => previous.map(message => (
    message.message_id === '42' ? { ...message, translationRetryAfter: now + 30_000 } : message
  )))

  const hasMore = messagesRef.current.some(message => !message.translated && isTranslationRetryEligible(message, now))
  assert.equal(hasMore, false)
  assert.equal(nextTranslationRetryDelay(messagesRef.current, now), 30_000)
  assert.equal(renderedMessages, messagesRef.current)
})

test('legacy delta scheduler coalesces ticks without invalidating the active request', async () => {
  const scheduler = createConversationDeltaScheduler()
  scheduler.activate('contact-a')
  const releases = []
  const starts = []
  const run = context => new Promise(resolve => {
    starts.push(context)
    releases.push(resolve)
  })
  const first = scheduler.trigger('contact-a', run)
  const second = scheduler.trigger('contact-a', run)
  assert.equal(starts.length, 1)
  assert.equal(starts[0].isCurrent(), true)
  releases.shift()()
  await Promise.resolve()
  assert.equal(starts.length, 2)
  releases.shift()()
  await Promise.all([first, second])
  assert.equal(starts.length, 2)
})

test('legacy delta scheduler rejects an old response after conversation switch', async () => {
  const scheduler = createConversationDeltaScheduler()
  scheduler.activate('contact-a')
  let oldContext
  let release
  const pending = scheduler.trigger('contact-a', context => new Promise(resolve => {
    oldContext = context
    release = resolve
  }))
  scheduler.activate('contact-b')
  assert.equal(oldContext.isCurrent(), false)
  release()
  await pending
})

test('legacy delta scheduler rerun consumes the latest callback closure', async () => {
  const scheduler = createConversationDeltaScheduler()
  scheduler.activate('contact-a')
  let release
  const calls = []
  const first = scheduler.trigger('contact-a', () => new Promise(resolve => {
    calls.push('old')
    release = resolve
  }))
  scheduler.trigger('contact-a', async () => { calls.push('latest') })
  release()
  await first
  assert.deepEqual(calls, ['old', 'latest'])
})
