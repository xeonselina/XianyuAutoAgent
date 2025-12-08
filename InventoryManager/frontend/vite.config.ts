import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import AutoImport from 'unplugin-auto-import/vite'
import Components from 'unplugin-vue-components/vite'
import { ElementPlusResolver } from 'unplugin-vue-components/resolvers'
import { fileURLToPath, URL } from 'node:url'

// https://vite.dev/config/
export default defineConfig({
  base: '/', // 使用绝对路径，这样在任何子路径下都能正确加载资源
  plugins: [
    vue(),
    // 自动导入 Vue API
    AutoImport({
      resolvers: [ElementPlusResolver()],
      imports: ['vue', 'vue-router', 'pinia'],
      dts: true
    }),
    // 自动导入组件
    Components({
      resolvers: [ElementPlusResolver()],
      dts: true
    })
  ],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url))
    }
  },
  server: {
    port: 5002,
    proxy: {
      // 代理 API 请求到 Flask 后端
      '/api': {
        target: 'http://localhost:5001',
        changeOrigin: true,
        rewrite: (path) => path
      },
      '/web': {
        target: 'http://localhost:5001',
        changeOrigin: true,
        rewrite: (path) => path
      }
    }
  },
  build: {
    outDir: '../static/vue-dist',
    emptyOutDir: true,
    rollupOptions: {
      output: {
        // 移除手动分块，让Vite自动处理依赖关系
        // manualChunks: {
        //   'element-plus': ['element-plus'],
        //   'vue-vendor': ['vue', 'vue-router', 'pinia']
        // }
      }
    },
    // 添加更严格的构建选项
    minify: 'esbuild',
    target: 'es2015'
  }
})