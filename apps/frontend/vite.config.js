import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

/**
 * Vite configuration for TuskerSquad dashboard.
 *
 * Proxy rules (dev server AND Docker container):
 *   /api/ui/*  → dashboard BFF  (VITE_DASH_URL or localhost:8501)
 *   /webhook/* → integration    (VITE_INTEGRATION_URL or localhost:8001)
 *
 * The browser always calls relative URLs — Vite proxies on the server side.
 * This works in npm run dev (host) and inside Docker without any change.
 */
export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    allowedHosts: 'all',
    proxy: {
      '/api/ui': {
        target: process.env.VITE_DASH_URL || 'http://localhost:8501',
        changeOrigin: true,
        // No rewrite — /api/ui/... passes through unchanged
      },
      '/webhook': {
        target: process.env.VITE_INTEGRATION_URL || 'http://localhost:8001',
        changeOrigin: true,
      },
    },
  },
})
