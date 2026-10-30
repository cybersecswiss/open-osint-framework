import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

/**
 * Build identity, injected into the bundle.
 *
 * The translation files are fetched at RUNTIME by i18next, so they are not
 * part of any hashed chunk and their URL never changes when their content
 * does. Combined with nginx serving them with no `Cache-Control`, a browser
 * applies heuristic caching and keeps showing yesterday's translations —
 * and behind a caching proxy/CDN the stale copy is served to everyone, not
 * just to whoever had it cached.
 *
 * Observed failure: a new tab rendered `admin.tab_notifications` as raw
 * text in English while the very same build showed the German, French and
 * Italian labels correctly — because those languages had never been
 * requested before and English had.
 *
 * Appending this to the loadPath makes every build a new URL. It costs one
 * ~90 kB refetch per deploy per language actually used, which is the
 * correct price for never shipping a stale translation again.
 */
const BUILD_ID = String(Date.now())

export default defineConfig({
  plugins: [react()],
  define: { __BUILD_ID__: JSON.stringify(BUILD_ID) },
  server: { port: 3000 },
  build: {
    outDir: 'dist',
    sourcemap: false,
    rollupOptions: {
      output: {
        /**
         * Vendor libraries in their own chunks.
         *
         * Route splitting (see `src/router.tsx`) decides what a user
         * downloads on their FIRST visit. This decides what they download
         * again on their SECOND — after a deploy.
         *
         * Without it, every rebuild produces one hashed bundle, so shipping
         * a one-line label fix makes every workstation re-download React,
         * AntD, Cytoscape and Leaflet. Those four change on our schedule
         * (rarely), the app code changes on ours (often); keeping them apart
         * means a routine deploy invalidates only the app chunk.
         *
         * Cytoscape and Leaflet are additionally the two heaviest libraries
         * in the tree and are each used by exactly one tab, so they stay out
         * of the initial load entirely.
         */
        manualChunks: {
          react: ['react', 'react-dom', 'react-router-dom'],
          antd: ['antd', '@ant-design/icons'],
          graph: ['cytoscape', 'cytoscape-fcose'],
          map: ['leaflet'],
        },
      },
    },
    // The graph and map chunks are legitimately large; the default 500 kB
    // warning would fire on every build and stop being read.
    chunkSizeWarningLimit: 900,
  },
})
