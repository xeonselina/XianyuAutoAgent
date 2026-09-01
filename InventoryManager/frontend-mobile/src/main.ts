import { createApp } from 'vue'
import { createPinia } from 'pinia'
import Vant from 'vant'
import 'vant/lib/index.css'
import App from './App.vue'
import { installTenantCsrfRecovery } from './api/csrfRecovery'
import router from './router'
import { useMobileAuthStore } from './stores/auth'

const app = createApp(App)
const pinia = createPinia()
app.use(pinia)
installTenantCsrfRecovery({
  refreshToken: () => useMobileAuthStore(pinia).refreshSession(),
  onInvalidSession: () => {
    useMobileAuthStore(pinia).clearSession()
    const next = `${window.location.pathname}${window.location.search}${window.location.hash}`
    window.location.replace(`/login?next=${encodeURIComponent(next)}`)
  },
})
app.use(router)
app.use(Vant)
app.mount('#app')
