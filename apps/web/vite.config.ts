/// <reference types="vitest/config" />
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The API runs separately (`make api`, port 8000); the dev server forwards /api to it, the
// session WebSocket included, so the app and the API share an origin as they will in production.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  // three.js + the VRM loader are one lazy chunk (~1.1 MB, ~290 kB gzipped), loaded only when
  // the avatar shows; the app itself stays far below this.
  build: { chunkSizeWarningLimit: 1200 },
  server: {
    proxy: {
      '/api': { target: 'http://localhost:8000', ws: true },
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test-setup.ts'],
    css: { include: [/index\.css/] }, // the contrast test reads the colour tokens from it
  },
})
