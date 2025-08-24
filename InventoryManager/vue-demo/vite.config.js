import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import AutoImport from 'unplugin-auto-import/vite'
import Components from 'unplugin-vue-components/vite'
import { ElementPlusResolver } from 'unplugin-vue-components/resolvers'

export default defineConfig({
  plugins: [
    vue(),
    // 自动导入Vue API
    AutoImport({
      resolvers: [ElementPlusResolver()],
      imports: ['vue', 'pinia'],
      dts: true
    }),
    // 自动导入组件
    Components({
      resolvers: [ElementPlusResolver()],
      dts: true
    })
  ],
  server: {
    port: 3000,
    proxy: {
      // 代理API请求到Flask后端
      '/api': {
        target: 'http://localhost:5000',
        changeOrigin: true
      }
    }
  },
  build: {
    outDir: '../static/vue-dist',
    emptyOutDir: true
  }
})
