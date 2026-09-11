import test from 'node:test'
import assert from 'node:assert/strict'
import { fileURLToPath } from 'node:url'
import React from 'react'
import { renderToString } from 'react-dom/server'
import { createServer } from 'vite'

const webRoot = fileURLToPath(new URL('../', import.meta.url))

test('critical settings routes render without ReferenceError', async t => {
  const server = await createServer({
    root: webRoot,
    appType: 'custom',
    logLevel: 'silent',
    server: { middlewareMode: true },
  })
  t.after(async () => server.close())

  const { default: SettingsPage } = await server.ssrLoadModule('/src/components/SettingsPage.jsx')
  const { default: SettingsPanel } = await server.ssrLoadModule('/src/components/SettingsPanel.jsx')

  for (const view of ['ai', 'chat']) {
    assert.doesNotThrow(() => renderToString(React.createElement(SettingsPage, {
      view,
      currentUser: { username: 'admin', role: 'admin' },
      apiSettings: {},
      webSettings: {},
      channels: [],
    })))
  }

  assert.doesNotThrow(() => renderToString(React.createElement(SettingsPanel, {
    open: true,
    settings: {},
    channels: [],
    onClose() {},
    onSave() {},
  })))
})
