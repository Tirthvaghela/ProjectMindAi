/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    // Proxy /api to Flask so the browser sees a single origin in development.
    // This sidesteps CORS entirely during dev; the backend's CORS config still
    // matters for any deployment where the two are served separately.
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:5000',
        changeOrigin: true,
      },
    },
  },
  // Vitest reuses this same Vite config (aliases, the react/tailwind
  // plugins) rather than a second config file — jsdom gives the component
  // tree a real DOM without a browser, and setupFiles wires in jest-dom's
  // matchers (toBeInTheDocument, etc.) globally.
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.js'],
    css: false,
  },
})
