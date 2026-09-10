import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

import { resolveDeploymentApiBase } from './deploymentEnv.js'

export default defineConfig(({ mode }) => {
  const tauriDevHost = process.env.TAURI_DEV_HOST
  const fileEnv = loadEnv(mode, process.cwd(), '')
  const configuredApiBase = process.env.VITE_API_BASE_URL ?? fileEnv.VITE_API_BASE_URL ?? ''
  const deploymentApiBase = resolveDeploymentApiBase({
    vercelEnv: process.env.VERCEL_ENV,
    configuredBase: configuredApiBase,
  })

  return {
    base: '/',
    plugins: [react()],
    clearScreen: false,
    // Vercel Production receives the reviewed public API origin without needing
    // a dashboard secret. Preview intentionally receives no production fallback.
    define: deploymentApiBase
      ? { 'import.meta.env.VITE_API_BASE_URL': JSON.stringify(deploymentApiBase) }
      : undefined,
    server: {
      host: tauriDevHost || '0.0.0.0',
      port: 38998,
      strictPort: true,
      hmr: tauriDevHost
        ? {
            protocol: 'ws',
            host: tauriDevHost,
            port: 38999,
          }
        : undefined,
      proxy: {
        '/api': {
          target: 'http://127.0.0.1:8792',
          changeOrigin: true,
        },
      },
    },
  }
})
