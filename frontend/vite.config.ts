import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// Where the proxy points. It can be redirected via NEXBRAND_API.
const apiTarget = process.env.NEXBRAND_API || 'http://127.0.0.1:8540'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: {
    rollupOptions: {
      output: {
        // Libraries change rarely. In their own file, they stay cached in the browser after an update.
        manualChunks(id) {
          if (id.includes('node_modules')) return 'vendor'
          return undefined
        },
      },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    css: false,
    exclude: ['node_modules/**', 'dist/**'],
    // A cold run (CI, no cache) translates each page on its first dynamic import inside a test, and a busy machine
    // stretches that past vitest's 5 s: 25 tests timed out on a fresh copy (05.10.2026). Waiting is no clock here,
    // the tests wait for answers; this only gives the first translation room.
    testTimeout: 30_000,
    hookTimeout: 30_000,
  },
  server: {
    // Fixed port: if it is taken, Vite aborts instead of silently falling back to another one.
    port: 5540,
    strictPort: true,
    proxy: {
      '/api': { target: apiTarget, changeOrigin: false },
    },
  },
  preview: {
    port: 5540,
    strictPort: true,
  },
})
