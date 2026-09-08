import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

const backendTarget = process.env.E2E_BACKEND_TARGET ?? 'http://localhost:5001'

export default defineConfig({
  base: '/mobile/',
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url))
    }
  },
  server: {
    port: 5003,
    proxy: {
      '/api': {
        target: backendTarget,
        changeOrigin: true
      },
      '/auth': {
        target: backendTarget,
        changeOrigin: true
      },
      '/web': {
        target: backendTarget,
        changeOrigin: true
      }
    }
  },
  build: {
    outDir: '../static/vue-mobile-dist',
    emptyOutDir: true,
    minify: 'oxc',
    target: 'es2015'
  }
})
