import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

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
  assert(segment.includes('https://whats.future1.us'), `${directive} must scope the production API/media origin explicitly`)
  assert(!segment.split(/\s+/).some(value => ['*', 'http:', 'https:'].includes(value)), `${directive} must not contain a network wildcard`)
}

assert(capability.identifier === 'main', 'main capability identifier is required')
assert(JSON.stringify(capability.windows) === JSON.stringify(['main']), 'capability must target only the main window')
assert(capability.permissions?.length === 1, 'native permissions must remain minimal')
const httpPermission = capability.permissions[0]
assert(httpPermission.identifier === 'http:default', 'only the scoped HTTP permission is expected')
assert(JSON.stringify(httpPermission.allow) === JSON.stringify([{ url: 'https://whats.future1.us/**' }]), 'HTTP permission must allow only the exact production origin')

const webProductionEnv = publicEnv('web/.env.production')
const tauriEnv = publicEnv('web/.env.tauri')
assert(JSON.stringify(Object.keys(webProductionEnv)) === JSON.stringify(['VITE_API_BASE']), 'browser production may expose only VITE_API_BASE')
assert(JSON.stringify(Object.keys(tauriEnv)) === JSON.stringify(['VITE_API_BASE']), 'Tauri mode may expose only VITE_API_BASE')
assert(webProductionEnv.VITE_API_BASE === '/api', 'browser production must keep a same-origin API base')
assert(tauriEnv.VITE_API_BASE === 'https://whats.future1.us/api', 'Tauri mode must use the approved remote API base')
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
assert(viteConfig.includes('process.env.TAURI_DEV_HOST'), 'physical mobile development host handling is missing')
assert(viteConfig.includes('strictPort: true'), 'Vite must not drift away from Tauri devUrl')
assert(!viteConfig.includes('allowedHosts: true'), 'Vite must not allow arbitrary Host headers')
for (const [name, vercel] of Object.entries({ root: rootVercel, web: webVercel })) {
  assert(vercel.rewrites?.[0]?.source === '/api/(.*)', `${name} Vercel deployment must preserve the same-origin API rewrite`)
}
assert(rootVercel.installCommand === 'npm ci --prefix web', 'root Vercel deployment must use the committed Web lockfile')

console.log('Tauri shell configuration validated without a Rust or mobile SDK')
