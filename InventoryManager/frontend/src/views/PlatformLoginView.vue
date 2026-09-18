<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { apiErrorMessage } from '@/api/auth'
import { useAuthStore } from '@/stores/auth'


const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const username = ref('')
const password = ref('')
const totp = ref('')
const busy = ref(false)
const errorMessage = ref('')

const login = async () => {
  busy.value = true
  errorMessage.value = ''
  try {
    await auth.verifyPlatform(username.value, password.value, totp.value)
    const next = route.query.next
    await router.replace(
      typeof next === 'string'
        && next.startsWith('/platform/')
        && !next.startsWith('//')
        ? next
        : '/platform/tenants',
    )
  } catch (error) {
    errorMessage.value = apiErrorMessage(error)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <main class="platform-login">
    <form @submit.prevent="login">
      <p class="eyebrow">Rental Manager · 平台控制台</p>
      <h1>超级管理员登录</h1>
      <p class="subtitle">登录后可创建客户店铺并设置首位店铺管理员。</p>
      <label>
        用户名
        <input v-model.trim="username" data-testid="platform-username" autocomplete="username">
      </label>
      <label>
        密码
        <input v-model="password" data-testid="platform-password" type="password" autocomplete="current-password">
      </label>
      <label>
        TOTP
        <input v-model.trim="totp" data-testid="platform-totp" inputmode="numeric" autocomplete="one-time-code">
      </label>
      <button type="submit" :disabled="busy">登录</button>
      <p v-if="errorMessage" class="error" role="alert">{{ errorMessage }}</p>
      <RouterLink class="tenant-entry" to="/login">返回店铺登录</RouterLink>
    </form>
  </main>
</template>

<style scoped>
.platform-login { min-height: 100vh; display: grid; place-items: center; padding: 24px; background: #101828; }
form { width: min(400px, 100%); display: grid; gap: 15px; padding: 32px; border-radius: 14px; background: white; }
form > p, h1 { margin: 0; }
.eyebrow { color: #175cd3; font-size: 12px; font-weight: 700; letter-spacing: .08em; }
.subtitle { color: #667085; font-size: 13px; line-height: 1.55; }
label { display: grid; gap: 7px; font-weight: 600; }
input { padding: 10px 12px; border: 1px solid #cbd5e1; border-radius: 8px; font: inherit; }
button { padding: 11px; border: 0; border-radius: 8px; color: white; background: #175cd3; font-weight: 700; }
.error { color: #b42318; }
.tenant-entry { padding-top: 14px; border-top: 1px solid #eaecf0; color: #667085; font-size: 13px; text-align: center; text-decoration: none; }
.tenant-entry:hover { color: #175cd3; }
</style>
