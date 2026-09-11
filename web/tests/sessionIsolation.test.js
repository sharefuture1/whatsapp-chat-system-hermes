import assert from 'node:assert/strict'
import test from 'node:test'
import { clearAllChatCaches, clearConversationCache, loadConversationCache,
  saveConversationCache, setChatCacheScope } from '../src/chatCache.js'

function fixture(t) {
  const data = new Map()
  const callbacks = []
  const original = { storage: globalThis.localStorage, idle: globalThis.requestIdleCallback }
  globalThis.localStorage = {
    get length() { return data.size },
    key: i => [...data.keys()][i], getItem: k => data.get(k) ?? null,
    setItem: (k, v) => data.set(k, v), removeItem: k => data.delete(k),
  }
  globalThis.requestIdleCallback = callback => { callbacks.push(callback); return callbacks.length }
  clearAllChatCaches()
  setChatCacheScope('alice')
  t.after(() => {
    clearAllChatCaches()
    for (const callback of callbacks.splice(0)) callback()
    globalThis.localStorage = original.storage
    globalThis.requestIdleCallback = original.idle
  })
  return { data, flush: () => { for (const cb of callbacks.splice(0)) cb() } }
}

test('SEC-CACHE-001 logout prevents idle work recreating deleted messages', t => {
  const { data, flush } = fixture(t)
  saveConversationCache('chat-a', [{ message_id: 'a', content: 'private A' }])
  clearAllChatCaches()
  flush()
  assert.equal(data.size, 0)
})

test('SEC-CACHE-001 scope switch cannot re-key old messages to the new user', t => {
  const { data, flush } = fixture(t)
  saveConversationCache('chat-a', [{ message_id: 'a', content: 'private A' }])
  setChatCacheScope('bob')
  flush()
  assert.equal(loadConversationCache('chat-a'), null)
  assert.equal([...data.values()].some(value => value.includes('private A')), false)
})

test('SEC-CACHE-001 deleting a conversation cancels its pending write only', t => {
  const { flush } = fixture(t)
  saveConversationCache('deleted', [{ message_id: 'a' }])
  saveConversationCache('kept', [{ message_id: 'b' }])
  clearConversationCache('deleted')
  flush()
  assert.equal(loadConversationCache('deleted'), null)
  assert.equal(loadConversationCache('kept').messages[0].message_id, 'b')
})

test('SEC-CACHE-001 stale callback cannot flush a newer session queue', t => {
  const { data, flush } = fixture(t)
  saveConversationCache('same', [{ message_id: 'old' }])
  clearAllChatCaches()
  setChatCacheScope('bob')
  saveConversationCache('same', [{ message_id: 'new' }])
  flush()
  assert.deepEqual(loadConversationCache('same').messages, [{ message_id: 'new' }])
  assert.equal([...data.keys()].some(k => k.includes(':alice:')), false)
})
