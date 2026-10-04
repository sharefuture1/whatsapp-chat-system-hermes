/**
 * 前端 API 基址解析：SDD VCL-002 要求权威变量名为 VITE_API_BASE_URL，
 * 历史名为 VITE_API_BASE。本测试锁定优先级、回退与向后兼容行为。
 */
import assert from 'node:assert/strict'
import test from 'node:test'

import { resolveApiBase } from '../src/api.js'

test('VCL-002: 优先使用 VITE_API_BASE_URL', () => {
  assert.equal(
    resolveApiBase({ VITE_API_BASE_URL: 'https://api.example.com/api' }),
    'https://api.example.com/api',
  )
})

test('VCL-002: 权威变量存在时忽略已弃用的旧变量', () => {
  assert.equal(
    resolveApiBase({
      VITE_API_BASE_URL: 'https://canonical.example.com/api',
      VITE_API_BASE: 'https://legacy.example.com/api',
    }),
    'https://canonical.example.com/api',
  )
})

test('向后兼容：仅设置旧变量时仍生效', () => {
  const originalWarn = console.warn
  const warnings = []
  console.warn = message => warnings.push(String(message))
  try {
    assert.equal(
      resolveApiBase({ VITE_API_BASE: 'https://legacy.example.com/api' }),
      'https://legacy.example.com/api',
    )
  } finally {
    console.warn = originalWarn
  }
  assert.equal(warnings.length, 1, '使用旧变量必须给出一次弃用告警')
  assert.match(warnings[0], /VITE_API_BASE_URL/)
})

test('两者都未设置时回退相对路径 /api（同源或反代部署）', () => {
  assert.equal(resolveApiBase({}), '/api')
})

test('空字符串与纯空白等同未设置', () => {
  assert.equal(resolveApiBase({ VITE_API_BASE_URL: '' }), '/api')
  assert.equal(resolveApiBase({ VITE_API_BASE_URL: '   ' }), '/api')
})

test('非字符串值被忽略，不会渲染成 [object Object]', () => {
  assert.equal(resolveApiBase({ VITE_API_BASE_URL: { url: 'x' } }), '/api')
  assert.equal(resolveApiBase({ VITE_API_BASE_URL: 123 }), '/api')
})

test('去除尾部斜杠，避免拼出 //v1/... 双斜杠', () => {
  assert.equal(
    resolveApiBase({ VITE_API_BASE_URL: 'https://api.example.com/api/' }),
    'https://api.example.com/api',
  )
})

test('去除首尾空白', () => {
  assert.equal(
    resolveApiBase({ VITE_API_BASE_URL: '  https://api.example.com/api  ' }),
    'https://api.example.com/api',
  )
})

test('保留路径内的斜杠结构', () => {
  assert.equal(
    resolveApiBase({ VITE_API_BASE_URL: 'https://example.com/prefix/api' }),
    'https://example.com/prefix/api',
  )
})
