import path from 'node:path';
import { mkdir, chmod } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';

export const LOOPBACK_HOSTS = new Set(['127.0.0.1', '::1', 'localhost']);

function positiveInteger(value, fallback, name) {
  const parsed = value === undefined ? fallback : Number(value);
  if (!Number.isSafeInteger(parsed) || parsed < 1) {
    throw new Error(`${name} must be a positive integer`);
  }
  return parsed;
}

async function secureDirectory(directory) {
  await mkdir(directory, { recursive: true, mode: 0o700 });
  await chmod(directory, 0o700);
}

export function loadConfig(env = process.env) {
  const canonicalToken = String(env.WHATSAPP_BRIDGE_INTERNAL_TOKEN ?? '').trim();
  const legacyToken = String(env.BRIDGE_INTERNAL_TOKEN ?? '').trim();
  if (canonicalToken && legacyToken && canonicalToken !== legacyToken) {
    throw new Error('WHATSAPP_BRIDGE_INTERNAL_TOKEN and BRIDGE_INTERNAL_TOKEN must match');
  }
  const internalToken = canonicalToken || legacyToken;
  if (!internalToken) throw new Error('Bridge internal token is required');

  const host = String(env.BRIDGE_HOST ?? '127.0.0.1').trim().toLowerCase();
  if (!LOOPBACK_HOSTS.has(host)) throw new Error('Bridge host must be loopback');

  const port = Number(env.BRIDGE_PORT ?? 3100);
  if (!Number.isInteger(port) || port < 0 || port > 65_535) {
    throw new Error('BRIDGE_PORT must be an integer between 0 and 65535');
  }

  const defaultRuntime = path.resolve(
    path.dirname(fileURLToPath(import.meta.url)),
    '..',
    'runtime',
    'whatsapp',
  );
  const runtimeRoot = path.resolve(env.BRIDGE_RUNTIME_ROOT || defaultRuntime);
  const sessionRoot = path.resolve(env.BRIDGE_SESSION_ROOT || path.join(runtimeRoot, 'sessions'));
  const spoolRoot = path.resolve(env.BRIDGE_SPOOL_ROOT || path.join(runtimeRoot, 'spool'));
  const mediaRoot = path.resolve(env.BRIDGE_MEDIA_ROOT || path.join(runtimeRoot, 'media'));

  if (new Set([sessionRoot, spoolRoot, mediaRoot]).size !== 3) {
    throw new Error('session, spool, and media roots must be distinct');
  }

  const eventUrl = String(
    env.WHATSAPP_EVENT_URL ?? 'http://127.0.0.1:8792/internal/events/whatsapp',
  ).trim();
  let parsedEventUrl;
  try {
    parsedEventUrl = new URL(eventUrl);
  } catch {
    throw new Error('WHATSAPP_EVENT_URL must be a valid URL');
  }
  if (parsedEventUrl.protocol !== 'http:' || !LOOPBACK_HOSTS.has(parsedEventUrl.hostname)) {
    throw new Error('WHATSAPP_EVENT_URL must use HTTP loopback');
  }
  if (parsedEventUrl.pathname !== '/internal/events/whatsapp') {
    throw new Error('WHATSAPP_EVENT_URL must target /internal/events/whatsapp');
  }

  return Object.freeze({
    internalToken,
    eventToken: internalToken,
    eventUrl: parsedEventUrl.toString(),
    host,
    port,
    runtimeRoot,
    sessionRoot,
    spoolRoot,
    mediaRoot,
    qrTtlMs: positiveInteger(env.BRIDGE_QR_TTL_MS, 60_000, 'BRIDGE_QR_TTL_MS'),
    async prepareRuntime() {
      await secureDirectory(runtimeRoot);
      await Promise.all([sessionRoot, spoolRoot, mediaRoot].map(secureDirectory));
    },
  });
}
