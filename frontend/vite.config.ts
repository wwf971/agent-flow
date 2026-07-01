import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const dirCurrent = dirname(fileURLToPath(import.meta.url))
const APP_BASE_ASSET_PLACEHOLDER = '/__APP_BASE__/'

export default defineConfig({
  base: APP_BASE_ASSET_PLACEHOLDER,
  plugins: [react()],
  resolve: {
    dedupe: ['react', 'react-dom'],
    alias: {
      react: resolve(dirCurrent, 'node_modules/react'),
      'react-dom': resolve(dirCurrent, 'node_modules/react-dom'),
      'react/jsx-runtime': resolve(dirCurrent, 'node_modules/react/jsx-runtime.js'),
      'react/jsx-dev-runtime': resolve(dirCurrent, 'node_modules/react/jsx-dev-runtime.js'),
    },
  },
  server: {
    proxy: {
      '/api': 'http://127.0.0.1:9410',
      '/login': 'http://127.0.0.1:9410',
      '/api/ws': {
        target: 'ws://127.0.0.1:9410',
        ws: true,
      },
    },
  },
})
