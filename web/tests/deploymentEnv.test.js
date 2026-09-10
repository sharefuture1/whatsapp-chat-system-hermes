import assert from 'node:assert/strict'
import test from 'node:test'

import {
  PRODUCTION_API_BASE,
  resolveDeploymentApiBase,
} from '../deploymentEnv.js'

test('VCL-002/VCL-005: Vercel Production 未配置时使用正式 API', () => {
  assert.equal(PRODUCTION_API_BASE, 'https://whats.wending.ai/api')
  assert.equal(
    resolveDeploymentApiBase({ vercelEnv: 'production', configuredBase: '' }),
    PRODUCTION_API_BASE,
  )
})

test('VCL-002: Vercel Production 显式配置也必须保持正式 API', () => {
  assert.throws(
    () => resolveDeploymentApiBase({
      vercelEnv: 'production',
      configuredBase: 'https://other.example.com/api',
    }),
    /Production API base must be/i,
  )
})

test('VCL-005: Vercel Preview 未配置时不得继承 Production API', () => {
  assert.equal(
    resolveDeploymentApiBase({ vercelEnv: 'preview', configuredBase: '' }),
    '',
  )
})

test('VCL-005: Vercel Preview 误配正式 API 时 fail-closed', () => {
  assert.throws(
    () => resolveDeploymentApiBase({
      vercelEnv: 'preview',
      configuredBase: 'https://whats.wending.ai/api/',
    }),
    /Preview.*production API/i,
  )
})

test('VCL-005: Vercel Preview 可显式使用 staging API', () => {
  assert.equal(
    resolveDeploymentApiBase({
      vercelEnv: 'preview',
      configuredBase: 'https://whats-staging.wending.ai/api/',
    }),
    'https://whats-staging.wending.ai/api',
  )
})

test('VCL-002: 非 Vercel 构建保留显式 API base，并规范尾部斜杠', () => {
  assert.equal(
    resolveDeploymentApiBase({
      vercelEnv: '',
      configuredBase: ' https://example.com/api/ ',
    }),
    'https://example.com/api',
  )
})
