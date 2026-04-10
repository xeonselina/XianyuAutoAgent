import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/knowledge': {
        target: 'http://localhost:8000',
        changeOrigin: true
      },
      '/prompts': {
        target: 'http://localhost:8000',
        changeOrigin: true
      },
      '/eval': {
        target: 'http://localhost:8000',
        changeOrigin: true
      },
      '/ignore-patterns': {
        target: 'http://localhost:8000',
        changeOrigin: true
      },
      '/conversations': {
        target: 'http://localhost:8000',
        changeOrigin: true
      }
    }
  },
  build: {
    outDir: 'dist',
    assetsDir: 'assets'
  }
})
