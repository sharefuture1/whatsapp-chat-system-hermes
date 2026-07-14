import test from 'node:test'
import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'

const read = path => readFileSync(new URL(`../src/${path}`, import.meta.url), 'utf8')

test('chat list and tab bar are memoized against unrelated re-renders', () => {
  const chatList = read('components/ChatList.jsx')
  assert.match(chatList, /import \{ memo/)
  assert.match(chatList, /export default memo\(ChatList\)/)

  const tabBar = read('components/TabBar.jsx')
  assert.match(tabBar, /import \{ memo \}/)
  assert.match(tabBar, /export default memo\(TabBar\)/)
})

test('App passes referentially stable props so ChatList/TabBar memo is effective', () => {
  const app = read('App.jsx')
  assert.match(app, /const contactProfileMap = useMemo/)
  assert.match(app, /const chatListAccounts = useMemo/)
  assert.match(app, /const handlePlatformFilterChange = useCallback/)
  assert.match(app, /const handleAccountFilterChange = useCallback/)
  assert.match(app, /const handleTabChange = useCallback/)
  assert.match(app, /selectedProfileMap=\{contactProfileMap\}/)
  assert.match(app, /accounts=\{chatListAccounts\}/)
  assert.match(app, /onPlatformFilterChange=\{handlePlatformFilterChange\}/)
  assert.match(app, /onAccountChange=\{handleAccountFilterChange\}/)
  assert.match(app, /onChange=\{handleTabChange\}/)
  // 内联 lambda 会击穿 memo，不得回归
  assert.doesNotMatch(app, /onPlatformFilterChange=\{platform =>/)
  assert.doesNotMatch(app, /accounts=\{inboxAccounts\.filter/)
})

test('keyboard focus ring and reduced-motion preference are honored (SDD-P2-04)', () => {
  const css = read('styles.css')
  assert.match(css, /:focus-visible/)
  assert.match(css, /outline: 2px solid var\(--wx-brand\)/)
  assert.match(css, /@media \(prefers-reduced-motion: reduce\)/)
  assert.match(css, /transition-duration: 0\.01ms !important/)
})

test('no editor backup files ship inside web/src', () => {
  assert.equal(existsSync(new URL('../src/i18n.js.bak', import.meta.url)), false)
})
