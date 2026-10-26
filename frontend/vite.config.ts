import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Set VITE_API_BASE_URL=/ to use one origin for the local UI and API.
// This avoids cross-origin preflights without relaxing backend CORS rules.
const apiProxy = {
  '/api': { target: 'http://127.0.0.1:3010', changeOrigin: true },
}

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: { proxy: apiProxy },
  preview: { proxy: apiProxy },
})
