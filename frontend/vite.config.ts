import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { fileURLToPath, URL } from 'node:url'

// The dev server proxies /api to the FastAPI backend so the SPA runs against a
// real API without CORS juggling; `pnpm build` emits into the backend's static
// dir so a single uvicorn process can serve the whole product.
export default defineConfig({
  plugins: [react()],
  resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
  server: {
    port: 5173,
    proxy: {
      '/api': { target: process.env.VITE_API_TARGET || 'http://127.0.0.1:8090', changeOrigin: true },
    },
  },
  build: {
    outDir: '../backend/app/static',
    emptyOutDir: true,
    sourcemap: false,
    chunkSizeWarningLimit: 900,
  },
})
