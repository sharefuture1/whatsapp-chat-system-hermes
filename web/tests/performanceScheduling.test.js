import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const read = path => readFileSync(new URL(`../src/${path}`, import.meta.url), 'utf8')

test('workspace polling is single-flight, completion-scheduled, and visibility aware', () => {
  const source = read('App.jsx')
  assert.match(source, /workspaceRefreshPromiseRef/)
  assert.match(source, /document\.visibilityState/)
  assert.match(source, /visibilitychange/)
  assert.match(source, /setTimeout\(run/)
  assert.doesNotMatch(source, /setInterval\(\(\) => refreshWorkspace/)
})

test('account polling is completion-scheduled and pauses in hidden tabs', () => {
  const source = read('accounts/useAccountsController.js')
  assert.match(source, /refreshPromiseRef/)
  assert.match(source, /document\.visibilityState/)
  assert.match(source, /visibilitychange/)
  assert.match(source, /setTimeout\(run/)
  assert.doesNotMatch(source, /setInterval\(\(\) => refresh/)
})

test('automatic translation uses one worker per active conversation', () => {
  const source = read('components/ChatPane.jsx')
  assert.match(source, /translationWorkerRunningRef/)
  assert.match(source, /translationGenerationRef/)
  assert.match(source, /!autoTranslate \|\| !userId \|\| translationWorkerRunningRef\.current/)
  assert.match(source, /new AbortController\(\)/)
  assert.match(source, /await translateOne\(msg, generation, controller\.signal\)/)
  assert.doesNotMatch(source, /for \(const msg of pending\.slice\(0, 6\)\)/)
})

test('successful send does not schedule a second full chat fetch with a naked timer', () => {
  const source = read('components/ChatPane.jsx')
  assert.doesNotMatch(source, /setTimeout\(\(\) => \{[\s\S]{0,180}fetchPage\(target, 1, false\)/)
})
