import assert from 'node:assert/strict';
import { mkdtemp, stat } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';

import { loadConfig } from '../src/config.js';

test('SEC-002: WHATSAPP_BRIDGE_INTERNAL_TOKEN is authoritative and legacy remains compatible', () => {
  assert.equal(loadConfig({ WHATSAPP_BRIDGE_INTERNAL_TOKEN: 'canonical' }).internalToken, 'canonical');
  assert.equal(loadConfig({ BRIDGE_INTERNAL_TOKEN: 'legacy' }).internalToken, 'legacy');
  assert.equal(loadConfig({
    WHATSAPP_BRIDGE_INTERNAL_TOKEN: 'same',
    BRIDGE_INTERNAL_TOKEN: 'same',
  }).internalToken, 'same');
});

test('SEC-002: conflicting canonical and legacy tokens fail closed', () => {
  assert.throws(
    () => loadConfig({
      WHATSAPP_BRIDGE_INTERNAL_TOKEN: 'canonical',
      BRIDGE_INTERNAL_TOKEN: 'legacy',
    }),
    /must match/i,
  );
});

test('SEC-002: missing internal token fails closed', () => {
  assert.throws(() => loadConfig({}), /internal token is required/i);
});

test('SEC-002: config rejects non-loopback bind host', () => {
  assert.throws(
    () => loadConfig({ BRIDGE_INTERNAL_TOKEN: 'secret', BRIDGE_HOST: '0.0.0.0' }),
    /loopback/i,
  );
});

test('API-EVENT: event endpoint defaults to FastAPI loopback and rejects external targets', () => {
  const config = loadConfig({ BRIDGE_INTERNAL_TOKEN: 'secret' });
  assert.equal(config.eventUrl, 'http://127.0.0.1:8792/internal/events/whatsapp');
  assert.equal(config.eventToken, 'secret');
  assert.throws(() => loadConfig({
    BRIDGE_INTERNAL_TOKEN: 'secret',
    WHATSAPP_EVENT_URL: 'https://example.com/internal/events/whatsapp',
  }), /loopback/i);
});

test('FR-ACC-003: runtime roots are distinct absolute 0700 directories', async () => {
  const runtime = await mkdtemp(path.join(os.tmpdir(), 'bridge-config-'));
  const config = loadConfig({
    BRIDGE_INTERNAL_TOKEN: 'secret',
    BRIDGE_RUNTIME_ROOT: runtime,
  });
  await config.prepareRuntime();

  assert.equal(path.isAbsolute(config.sessionRoot), true);
  assert.equal(path.isAbsolute(config.spoolRoot), true);
  assert.equal(path.isAbsolute(config.mediaRoot), true);
  assert.equal(new Set([config.sessionRoot, config.spoolRoot, config.mediaRoot]).size, 3);
  for (const root of [config.sessionRoot, config.spoolRoot, config.mediaRoot]) {
    assert.equal((await stat(root)).mode & 0o777, 0o700);
  }
});
