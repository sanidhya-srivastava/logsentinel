import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const proxyTarget = (envKey, fallback) => globalThis.process?.env?.[envKey] || fallback

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api/dashboard': {
        target: proxyTarget('VITE_DASHBOARD_PROXY_TARGET', 'http://127.0.0.1:8002'),
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api\/dashboard/, ''),
      },
      '/api/ml': {
        target: proxyTarget('VITE_ML_PROXY_TARGET', 'http://127.0.0.1:8001'),
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api\/ml/, ''),
      },
      '/api/ingest': {
        target: proxyTarget('VITE_INGEST_PROXY_TARGET', 'http://127.0.0.1:8000'),
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api\/ingest/, ''),
      },
    },
  },
})
