import assert from 'node:assert/strict'
import test from 'node:test'
import { createRefreshCoordinator, mergeConversationPages } from '../src/workspaceRefresh.js'

test('pagination append merges by real conversation identity instead of replacing', () => {
  assert.deepEqual(mergeConversationPages(
    [{ conversation_key: 'a', value: 1 }],
    [{ conversation_key: 'b', value: 2 }], true,
  ).map(item => item.conversation_key), ['a', 'b'])
})

test('fresh refresh after a mutation never reuses the pre-mutation inflight request', async () => {
  const coordinator = createRefreshCoordinator()
  let resolveOld
  const committed = []
  const old = coordinator.run(() => new Promise(resolve => { resolveOld = resolve }), value => committed.push(value))
  const fresh = coordinator.run(() => Promise.resolve('fresh'), value => committed.push(value), { fresh: true })
  assert.notEqual(old, fresh)
  assert.equal(await fresh, 'fresh')
  resolveOld('old')
  await old
  assert.deepEqual(committed, ['fresh'])
})

test('ordinary refreshes coalesce and commit the shared result once', async () => {
  const coordinator = createRefreshCoordinator()
  const committed = []
  let resolveRequest
  const factory = () => new Promise(resolve => { resolveRequest = resolve })
  const first = coordinator.run(factory, value => committed.push(value))
  const second = coordinator.run(factory, value => committed.push(value))
  assert.equal(first, second)
  await Promise.resolve()
  resolveRequest('shared')
  assert.equal(await first, 'shared')
  assert.deepEqual(committed, ['shared'])
})
