/**
 * 移动端前端入口文件
 */

import { createApp } from 'vue'
import { createPinia } from 'pinia'
import router from './router'
import App from './App.vue'

// Vant样式
import 'vant/lib/index.css'

// 创建应用
const app = createApp(App)

// 注册插件
app.use(createPinia())
app.use(router)

// 挂载应用
app.mount('#app')
