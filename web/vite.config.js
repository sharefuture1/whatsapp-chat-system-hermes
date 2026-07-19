import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const tauriDevHost = process.env.TAURI_DEV_HOST

export default defineConfig({
  base: '/',
  plugins: [react()],
  clearScreen: false,
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
})
