import tailwindcss from '@tailwindcss/vite'
import { tanstackRouter } from '@tanstack/router-plugin/vite'
import react from '@vitejs/plugin-react'
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vitest/config'

// Ports 8741 (dev) and 8742 (e2e preview) belong to glassdesk (AGENTS.md); /api goes to the backend.
const api = { '/api': { target: 'http://127.0.0.1:8740', changeOrigin: false } }

export default defineConfig(({ mode }) => ({
  plugins: [tanstackRouter({ target: 'react', autoCodeSplitting: mode !== 'test' }), react(), tailwindcss()],
  resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
  server: { port: 8741, strictPort: true, host: '127.0.0.1', proxy: api },
  preview: { port: 8742, strictPort: true, host: '127.0.0.1' },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
    css: false,
    globals: true,
  },
}))
