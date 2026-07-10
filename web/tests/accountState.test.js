import test from 'node:test'
import assert from 'node:assert/strict'

import {
  mergeAccountEvent,
  normalizeAccount,
  summarizeAccounts,
  statusMeta,
} from '../src/accounts/accountState.js'

test('normalizeAccount keeps server state as truth and adds no fake online state', () => {
  const account = normalizeAccount({ id: 'a', name: 'Sales', status: 'new' })
  assert.equal(account.status, 'new')
  assert.equal(account.enabled, true)
  assert.equal(account.is_primary, false)
})

test('mergeAccountEvent only updates the matching account', () => {
  const accounts = [
    normalizeAccount({ id: 'a', name: 'A', status: 'online', updated_at: '2026-07-10T10:00:00Z' }),
    normalizeAccount({ id: 'b', name: 'B', status: 'offline', updated_at: '2026-07-10T10:00:00Z' }),
  ]
  const next = mergeAccountEvent(accounts, {
    event_id: 'evt-1', account_id: 'b', occurred_at: '2026-07-10T10:01:00Z',
    payload: { status: 'online' },
  }, new Set())
  assert.equal(next.accounts[0].status, 'online')
  assert.equal(next.accounts[1].status, 'online')
  assert.equal(next.applied, true)
})

test('mergeAccountEvent ignores duplicate and stale events', () => {
  const seen = new Set(['evt-1'])
  const accounts = [normalizeAccount({
    id: 'a', name: 'A', status: 'online', updated_at: '2026-07-10T10:02:00Z',
  })]
  assert.equal(mergeAccountEvent(accounts, {
    event_id: 'evt-1', account_id: 'a', occurred_at: '2026-07-10T10:03:00Z', payload: { status: 'offline' },
  }, seen).applied, false)
  assert.equal(mergeAccountEvent(accounts, {
    event_id: 'evt-2', account_id: 'a', occurred_at: '2026-07-10T10:01:00Z', payload: { status: 'offline' },
  }, seen).applied, false)
})

test('summarizeAccounts reports online and attention counts', () => {
  const result = summarizeAccounts([
    normalizeAccount({ id: 'a', name: 'A', status: 'online' }),
    normalizeAccount({ id: 'b', name: 'B', status: 'error' }),
    normalizeAccount({ id: 'c', name: 'C', status: 'logged_out', enabled: false }),
  ])
  assert.deepEqual(result, { total: 3, online: 1, attention: 2, enabled: 2 })
})

test('statusMeta has safe fallback for unknown server status', () => {
  assert.equal(statusMeta('unknown').key, 'accountStatusUnknown')
  assert.equal(statusMeta('online').tone, 'online')
})
