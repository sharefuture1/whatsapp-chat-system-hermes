// SEC-AUTH-015: real browser rendering with isolated API responses, no production traffic.
import assert from 'node:assert/strict'
import { createServer } from 'node:http'
import { readFile } from 'node:fs/promises'
import { resolve, extname } from 'node:path'
import { chromium } from 'playwright'

const dist = resolve(new URL('../dist', import.meta.url).pathname)
const server = createServer(async (req, res) => {
  try {
    const path = decodeURIComponent(new URL(req.url, 'http://localhost').pathname)
    const file = resolve(dist, `.${path === '/' ? '/index.html' : path}`)
    if (!file.startsWith(`${dist}/`)) { res.writeHead(403); res.end(); return }
    const body = await readFile(file)
    const mime = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml' }
    res.writeHead(200, { 'Content-Type': mime[extname(file)] || 'application/octet-stream' })
    res.end(body)
  } catch { res.writeHead(404); res.end() }
})
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve))
const origin = `http://127.0.0.1:${server.address().port}`
const browser = await chromium.launch({
  executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH || undefined,
  headless: true, args: ['--no-sandbox'],
})
try {
  const source = await readFile(new URL('../src/App.jsx', import.meta.url), 'utf8')
  const tokenKey = source.match(/const TOKEN_KEY\s*=\s*['"]([^'"]+)['"]/)?.[1]
  assert.ok(tokenKey)
  for (const viewport of [{ width: 390, height: 844 }, { width: 1366, height: 900 }]) {
    const context = await browser.newContext({ viewport })
    const page = await context.newPage()
    const pageErrors = []
    const businessRequests = []
    let passwordChanges = 0
    page.on('pageerror', error => pageErrors.push(error.message))
    await context.addInitScript(({ tokenKey }) => {
      localStorage.setItem(tokenKey, 'isolated-browser-test-token')
      localStorage.setItem('chat-system-language-v2', 'zh')
    }, { tokenKey })
    await page.route('**/api/**', async route => {
      const path = new URL(route.request().url()).pathname
      let body
      if (path === '/api/health') body = { ok: true, login_enabled: true, runtime_mode: 'standalone' }
      else if (path === '/api/v1/me') body = { username: 'test-user', role: 'operator', password_change_required: true }
      else if (path === '/api/v1/users/change-password') { passwordChanges += 1; body = { password_changed: true } }
      else if (path === '/api/logout') body = { success: true }
      else { businessRequests.push(path); body = { detail: { code: 'password_change_required' } } }
      await route.fulfill({ status: body.detail ? 403 : 200, contentType: 'application/json', body: JSON.stringify(body) })
    })
    await page.goto(origin)
    const form = page.locator('[data-testid="force-password"]')
    await form.waitFor({ state: 'visible', timeout: 3000 })
    assert.deepEqual(businessRequests, [], 'restricted users must not start workspace data loading')
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false)
    await form.locator('input[name="old_password"]').fill('old-test-password')
    await form.locator('input[name="new_password"]').fill('new-test-password')
    await form.locator('input[name="confirm_password"]').fill('different-test-password')
    await form.locator('button[type="submit"]').click()
    assert.equal(passwordChanges, 0, 'mismatched passwords must not reach the API')
    await form.locator('input[name="confirm_password"]').fill('new-test-password')
    await form.locator('button[type="submit"]').click()
    await form.waitFor({ state: 'detached', timeout: 3000 })
    assert.equal(passwordChanges, 1)
    assert.equal(await page.evaluate(key => localStorage.getItem(key), tokenKey), null)
    assert.deepEqual(pageErrors, [])
    await context.close()
    console.log(`PASS mandatory password change ${viewport.width}x${viewport.height}`)
  }
} finally {
  await browser.close()
  await new Promise(resolve => server.close(resolve))
}
