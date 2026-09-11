import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import test from 'node:test'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const read = path => readFileSync(resolve(root, path), 'utf8')

test('FR-CON-013: chat list renders synced avatar_url with initials fallback', () => {
  const source = read('src/components/ChatList.jsx')
  assert.match(source, /item\.avatar_url/)
  assert.match(source, /ContactAvatar/)
  assert.match(source, /onError/)
})

test('FR-CON-013: chat pane receives avatarUrl and uses it for remote contact surfaces', () => {
  const pane = read('src/components/ChatPane.jsx')
  const app = read('src/App.jsx')
  assert.match(pane, /avatarUrl/)
  assert.match(pane, /RemoteAvatar/)
  assert.match(app, /avatarUrl=\{selectedConversation\?\.avatar_url/)
})
