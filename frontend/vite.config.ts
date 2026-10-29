import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import { createLocalDemoPlugin } from './server/localDemo.mjs'

const repositoryRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')

// Set VITE_API_BASE_URL=/ to use one origin for the local UI and API.
// This avoids cross-origin preflights without relaxing backend CORS rules.
const apiProxy = {
  '/api': { target: 'http://127.0.0.1:3010', changeOrigin: true },
}

// https://vite.dev/config/
export default defineConfig(({ mode }) => ({
  define: { 'import.meta.env.VITE_RUNTIME_MODE': JSON.stringify(mode === 'browser' ? 'browser' : 'server') },
  plugins: [react(), ...(mode === 'browser' ? [createLocalDemoPlugin(loadEnv(mode, repositoryRoot, 'DEMO_'))] : [])],
  server: { proxy: apiProxy },
  preview: { proxy: apiProxy },
}))
