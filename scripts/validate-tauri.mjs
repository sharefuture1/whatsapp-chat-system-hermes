import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import { PRODUCTION_API_BASE, resolveDeploymentApiBase } from '../web/deploymentEnv.js'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')

function read(path) {
  return readFileSync(resolve(root, path), 'utf8')
}

function readJson(path) {
  return JSON.parse(read(path))
}

function assert(condition, message) {
  if (!condition) throw new Error(message)
}

function publicEnv(path) {
  const values = {}
  for (const rawLine of read(path).split(/\r?\n/)) {
    const line = rawLine.trim()
    if (!line || line.startsWith('#')) continue
    const separator = line.indexOf('=')
    assert(separator > 0, `${path} contains an invalid environment line`)
    values[line.slice(0, separator).trim()] = line.slice(separator + 1).trim()
  }
  return values
}

const rootPackage = readJson('package.json')
const webPackage = readJson('web/package.json')
const config = readJson('src-tauri/tauri.conf.json')
const capability = readJson('src-tauri/capabilities/main.json')
const rootVercel = readJson('vercel.json')
const webVercel = readJson('web/vercel.json')

assert(rootPackage.scripts?.['web:build:tauri'] === 'npm --prefix web run build:tauri', 'root Tauri frontend build script changed unexpectedly')
assert(rootPackage.scripts?.['tauri:validate'] === 'node scripts/validate-tauri.mjs', 'root Tauri validation script is missing')
assert(rootPackage.devDependencies?.['@tauri-apps/cli']?.startsWith('2.'), 'Tauri CLI must stay on major version 2')
assert(webPackage.scripts?.['build:tauri'] === 'vite build --mode tauri', 'Web Tauri Vite mode is missing')
assert(webPackage.dependencies?.['@tauri-apps/api']?.startsWith('2.'), 'Tauri JavaScript API must stay on major version 2')
assert(webPackage.dependencies?.['@tauri-apps/plugin-http']?.startsWith('2.'), 'Tauri HTTP plugin must stay on major version 2')

assert(config.$schema === 'https://schema.tauri.app/config/2', 'Tauri v2 schema reference is required')
assert(config.identifier === 'us.future1.hermes.messaging', 'bundle identifier changed; review store identity before changing it')
assert(config.build?.devUrl === 'http://localhost:38998', 'Tauri devUrl must match the strict Vite port')
assert(config.build?.frontendDist === '../web/dist', 'Tauri frontendDist must embed the existing Web build')
assert(config.build?.beforeBuildCommand === 'npm run web:build:tauri', 'Tauri release builds must use the isolated Vite mode')
assert(JSON.stringify(config.app?.security?.capabilities) === JSON.stringify(['main']), 'only the reviewed main capability may be enabled')
const mainWindow = config.app?.windows?.find(window => window.label === 'main')
assert(mainWindow?.useHttpsScheme === true, 'main window must keep its secure scheme setting')
assert(mainWindow?.minWidth == null && mainWindow?.minHeight == null, 'native window minimums must not force a desktop viewport on phones')

const csp = config.app?.security?.csp || ''
for (const directive of ['connect-src', 'img-src', 'media-src']) {
  const segment = csp.split(';').find(value => value.trim().startsWith(directive)) || ''
  assert(segment.includes('https://whats.wending.ai'), `${directive} must scope the production API/media origin explicitly`)
  assert(!segment.includes('https://whats.future1.us'), `${directive} must not retain the retired production API origin`)
  assert(!segment.split(/\s+/).some(value => ['*', 'http:', 'https:'].includes(value)), `${directive} must not contain a network wildcard`)
}

assert(capability.identifier === 'main', 'main capability identifier is required')
assert(JSON.stringify(capability.windows) === JSON.stringify(['main']), 'capability must target only the main window')
assert(capability.permissions?.length === 1, 'native permissions must remain minimal')
const httpPermission = capability.permissions[0]
assert(httpPermission.identifier === 'http:default', 'only the scoped HTTP permission is expected')
assert(JSON.stringify(httpPermission.allow) === JSON.stringify([{ url: 'https://whats.wending.ai/api/**' }]), 'HTTP permission must allow only the exact production API path')

const webProductionEnv = publicEnv('web/.env.production')
const tauriEnv = publicEnv('web/.env.tauri')
// 权威变量名是 VITE_API_BASE_URL（SDD VCL-002）。旧名 VITE_API_BASE 仍被
// api.js 识别为兼容别名，但不得再作为仓库中的配置源。
const expectedApiBaseKey = 'VITE_API_BASE_URL'
assert(Object.keys(webProductionEnv).length === 0, 'browser .env.production must not force Preview deployments onto the production API')
assert(JSON.stringify(Object.keys(tauriEnv)) === JSON.stringify([expectedApiBaseKey]), `Tauri mode may expose only ${expectedApiBaseKey}`)
assert(tauriEnv[expectedApiBaseKey] === 'https://whats.wending.ai/api', 'Tauri mode must use the approved remote API base')
assert(webProductionEnv.VITE_API_BASE == null && tauriEnv.VITE_API_BASE == null, 'legacy VITE_API_BASE must not be reintroduced as a configuration source')
for (const [path, values] of Object.entries({ 'web/.env.production': webProductionEnv, 'web/.env.tauri': tauriEnv })) {
  for (const key of Object.keys(values)) {
    assert(!/(?:PASSWORD|TOKEN|SECRET|PRIVATE_KEY|API_KEY)/i.test(key), `${path} must not contain client-bundled credentials`)
  }
}

const cargo = read('src-tauri/Cargo.toml')
const rustEntry = read('src-tauri/src/lib.rs')
const apiClient = read('web/src/api.js')
const viteConfig = read('web/vite.config.js')
assert(/^tauri-plugin-http\s*=\s*"2"\s*$/m.test(cargo), 'Rust HTTP plugin dependency is missing')
assert(/^rust-version\s*=\s*"1\.77\.2"\s*$/m.test(cargo), 'Tauri HTTP plugin minimum Rust version must stay explicit')
assert(rustEntry.includes('.plugin(tauri_plugin_http::init())'), 'Rust HTTP plugin is not initialized')
assert(apiClient.includes("from '@tauri-apps/plugin-http'"), 'Web API client is not wired to the Tauri HTTP plugin')
assert(apiClient.includes('globalThis.fetch'), 'browser fetch fallback must remain available')
assert(PRODUCTION_API_BASE === 'https://whats.wending.ai/api', 'Vercel production fallback must use the approved API origin')
assert(resolveDeploymentApiBase({ vercelEnv: 'production' }) === PRODUCTION_API_BASE, 'Vercel Production must resolve the approved API origin')
let previewProductionRejected = false
try {
  resolveDeploymentApiBase({ vercelEnv: 'preview', configuredBase: PRODUCTION_API_BASE })
} catch {
  previewProductionRejected = true
}
assert(previewProductionRejected, 'Vercel Preview must reject the production API origin')
assert(viteConfig.includes('resolveDeploymentApiBase'), 'Vite config must apply the deployment API resolver')
assert(viteConfig.includes('process.env.TAURI_DEV_HOST'), 'physical mobile development host handling is missing')
assert(viteConfig.includes('strictPort: true'), 'Vite must not drift away from Tauri devUrl')
assert(!viteConfig.includes('allowedHosts: true'), 'Vite must not allow arbitrary Host headers')
// 前端改为直连 API（VITE_API_BASE_URL 注入绝对地址），因此 Vercel 侧不再需要
// `/api` 代理改写。这里保留护栏的**反向**形式：任何把 /api 代理到第三方域的
// rewrite 都不允许回归，否则又会把后端地址硬编码进部署配置。
for (const [name, vercel] of Object.entries({ root: rootVercel, web: webVercel })) {
  const rewrites = vercel.rewrites ?? []
  assert(rewrites.length === 1, `${name} Vercel deployment must keep only the SPA fallback rewrite`)
  assert(rewrites[0].source === '/((?!api/).*)', `${name} Vercel deployment must keep the SPA fallback rewrite`)
  assert(rewrites[0].destination === '/index.html', `${name} SPA fallback must target index.html`)
  for (const rewrite of rewrites) {
    assert(!/\/api\//.test(rewrite.source ?? ''), `${name} must not proxy /api requests to a third-party host`)
    assert(!/https?:\/\//.test(rewrite.destination ?? ''), `${name} rewrite must not hardcode an external destination`)
  }
}
assert(rootVercel.installCommand === 'npm ci --prefix web', 'root Vercel deployment must use the committed Web lockfile')

console.log('Tauri shell configuration validated without a Rust or mobile SDK')
