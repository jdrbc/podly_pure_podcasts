import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// For development, the frontend development server will proxy to the backend
// The backend port should match the configured application port
// This will work with the new port configuration
const BACKEND_TARGET = 'http://localhost:5001'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: true,
    allowedHosts: true,
    proxy: {
      '/api': {
        target: BACKEND_TARGET,
        changeOrigin: true,
        secure: false
      },
      // Proxy feed endpoints for backwards compatibility
      '/feed': {
        target: BACKEND_TARGET,
        changeOrigin: true,
        secure: false
      },
      // Proxy legacy post endpoints for backwards compatibility
      '/post': {
        target: BACKEND_TARGET,
        changeOrigin: true,
        secure: false
      }
    }
  },
  build: {
    outDir: 'dist',
    sourcemap: false
  }
})
