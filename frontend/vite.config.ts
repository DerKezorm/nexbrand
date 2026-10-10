import { createHash } from 'node:crypto'
import { readFileSync } from 'node:fs'
import { defineConfig, type Plugin } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// Where the proxy points. It can be redirected via NEXBRAND_API.
const apiTarget = process.env.NEXBRAND_API || 'http://127.0.0.1:8540'

/** The tab's icon with its checksum in the address. A browser keeps a tab icon per address and does not ask again,
 * so an icon that changed under the same address stayed old in the tab (nextasks showed the nexcanvas shapes from its
 * start long after, found 06.10.2026). */
function iconWithChecksum(): Plugin {
  return {
    name: 'icon-with-checksum',
    transformIndexHtml(html) {
      const sum = createHash('sha256').update(readFileSync(new URL('./public/logo.svg', import.meta.url))).digest('hex').slice(0, 12)
      return html.replace('href="/logo.svg"', `href="/logo.svg?v=${sum}"`)
    },
  }
}

export default defineConfig({
  plugins: [react(), tailwindcss(), iconWithChecksum()],
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
    // The end-to-end tests run in Playwright (`npm run e2e`), not here.
    exclude: ['node_modules/**', 'dist/**', 'e2e/**'],
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
