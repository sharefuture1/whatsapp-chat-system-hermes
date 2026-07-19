import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

import { mergeFreshMessages, sameMessageList } from '../src/chatSync.js'

const read = path => readFileSync(new URL(`../src/${path}`, import.meta.url), 'utf8')

test('PERF-001: refresh interval respects server setting, clamped to [3,300], default 5s', () => {
  const app = read('App.jsx')
  assert.doesNotMatch(app, /Math\.max\(30/, '30s 下限钳制不得回归')
  assert.match(app, /Math\.min\(300, Math\.max\(3, autoSeconds\)\)/)
  assert.match(app, /: 5\b/, '缺失/非法配置必须默认 5 秒，不得解释为关闭轮询')
})

test('PERF-002: regular polling fetches conversations only, without contacts', () => {
  const app = read('App.jsx')
  assert.doesNotMatch(app, /limit=200`\)/, '轮询不得固定拉取 200 条会话')
  assert.match(app, /CONVERSATIONS_PAGE_LIMIT = 50/)
  const fetchBlock = app.slice(app.indexOf('const fetchConversationsPage'), app.indexOf('const loadContacts'))
  assert.doesNotMatch(fetchBlock, /v1\/contacts/, 'contacts 不得随常规轮询拉取')
  assert.match(app, /const loadContacts = useCallback/)
  assert.match(app, /activeTab === 'contacts'\) loadContacts\(\)/)
})

test('PERF-008: mergeFreshMessages keeps the previous array reference when nothing changed', () => {
  const current = [
    { message_id: '1', role: 'user', content: 'hi', timestamp: 100, status: 'received' },
    { message_id: '2', role: 'assistant', content: 'hello', timestamp: 200, status: 'sent', sent: true },
  ]
  const server = current.map(item => ({ ...item }))
  const merged = mergeFreshMessages(server, current)
  assert.equal(merged, current, '服务端数据未变化时必须返回原数组引用')

  const changed = mergeFreshMessages(
    [...server, { message_id: '3', role: 'user', content: 'new', timestamp: 300 }],
    current,
  )
  assert.notEqual(changed, current)
  assert.equal(changed.length, 3)
})

test('PERF-008: sameMessageList detects field-level changes', () => {
  const a = [{ message_id: '1', content: 'x', translated: null }]
  const b = [{ message_id: '1', content: 'x', translated: '译' }]
  assert.equal(sameMessageList(a, a), true)
  assert.equal(sameMessageList(a, b), false)
})

test('PERF-008: mergeFreshMessages preserves server reconciliation and media changes', () => {
  const current = [{
    message_id: '1',
    role: 'assistant',
    content: 'x',
    status: 'sent',
    platform_message_id: null,
    media_metadata: { url: 'old' },
  }]
  const server = [{
    ...current[0],
    platform_message_id: 'wa-1',
    media_metadata: { url: 'new' },
  }]
  const merged = mergeFreshMessages(server, current)
  assert.notEqual(merged, current)
  assert.equal(merged[0].platform_message_id, 'wa-1')
  assert.deepEqual(merged[0].media_metadata, { url: 'new' })
})

test('PERF-008: conversation cache writes are deferred off the critical path', () => {
  const cache = read('chatCache.js')
  assert.match(cache, /requestIdleCallback/)
  assert.match(cache, /pendingCacheWrites/)
})

test('PERF-008: chat pane always revalidates against the server (cache is skeleton only)', () => {
  const pane = read('components/ChatPane.jsx')
  assert.doesNotMatch(pane, /isConversationCacheFresh/, '缓存新鲜度不得再短路网络请求')
})

test('UI: chat list shows loading skeleton on first workspace load', () => {
  const chatList = read('components/ChatList.jsx')
  assert.match(chatList, /ListSkeleton/)
  assert.match(chatList, /loading && conversations\.length === 0/)
  const app = read('App.jsx')
  assert.match(app, /loading=\{workspaceLoading\}/)
  const css = read('styles.css')
  assert.match(css, /\.wx-list-skeleton-row/)
})
