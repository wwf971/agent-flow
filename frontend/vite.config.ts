import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const dirCurrent = dirname(fileURLToPath(import.meta.url))

const normalizeBasePath = (rawBasePath: string | undefined): string => {
  const trimmed = `${rawBasePath ?? ''}`.trim()
  if (!trimmed || trimmed === '/') {
    return '/'
  }
  const withLeadingSlash = trimmed.startsWith('/') ? trimmed : `/${trimmed}`
  return withLeadingSlash.endsWith('/') ? withLeadingSlash : `${withLeadingSlash}/`
}

const appBasePath = normalizeBasePath(process.env.VITE_APP_BASE_PATH)

export default defineConfig({
  base: appBasePath,
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
