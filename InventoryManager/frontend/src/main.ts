import './assets/main.css'

import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import 'element-plus/theme-chalk/dark/css-vars.css'
import * as ElementPlusIconsVue from '@element-plus/icons-vue'
import zhCn from 'element-plus/es/locale/lang/zh-cn'

import App from './App.vue'
import { installTenantCsrfRecovery } from './api/csrfRecovery'
import router from './router'
import { useAuthStore } from './stores/auth'

const app = createApp(App)
const pinia = createPinia()

// 注册 Element Plus 图标
for (const [key, component] of Object.entries(ElementPlusIconsVue)) {
  app.component(key, component)
}

app.use(pinia)
installTenantCsrfRecovery({
  refreshToken: async () => {
    const auth = useAuthStore(pinia)
    if (!await auth.refreshTenantSession()) return null
    return auth.csrfToken
  },
  onInvalidSession: () => {
    useAuthStore(pinia).clearTenantSession()
    const next = `${window.location.pathname}${window.location.search}${window.location.hash}`
    window.location.replace(`/login?next=${encodeURIComponent(next)}`)
  },
})
app.use(router)
app.use(ElementPlus, {
  locale: zhCn,
})

app.mount('#app')
