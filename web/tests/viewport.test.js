import test from 'node:test'
import assert from 'node:assert/strict'

import { installViewportHeightSync, readViewportHeight } from '../src/viewport.js'

function eventTarget(initial = {}) {
  const listeners = new Map()
  return {
    ...initial,
    addEventListener(type, listener) {
      const bucket = listeners.get(type) || new Set()
      bucket.add(listener)
      listeners.set(type, bucket)
    },
    removeEventListener(type, listener) {
      listeners.get(type)?.delete(listener)
    },
    emit(type) {
      for (const listener of listeners.get(type) || []) listener()
    },
  }
}

test('viewport height prefers visualViewport and falls back to innerHeight', () => {
  assert.equal(readViewportHeight({ visualViewport: { height: 512.4 }, innerHeight: 800 }), 512)
  assert.equal(readViewportHeight({ visualViewport: { height: 0 }, innerHeight: 799.6 }), 800)
  assert.equal(readViewportHeight({}), null)
})
test('viewport sync tracks mobile keyboard resizes and can be cleaned up', () => {
  const visualViewport = eventTarget({ height: 640 })
  const view = eventTarget({ innerHeight: 800, visualViewport })
  const values = []
  const root = { style: { setProperty: (name, value) => values.push([name, value]) } }

  const cleanup = installViewportHeightSync(view, root)
  assert.deepEqual(values.at(-1), ['--app-viewport-height', '640px'])

  visualViewport.height = 412
  visualViewport.emit('resize')
  assert.deepEqual(values.at(-1), ['--app-viewport-height', '412px'])

  cleanup()
  visualViewport.height = 700
  visualViewport.emit('resize')
  assert.deepEqual(values.at(-1), ['--app-viewport-height', '412px'])
})
