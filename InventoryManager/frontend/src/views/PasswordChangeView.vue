<script setup lang="ts">
import { ref } from 'vue'

import { apiErrorMessage } from '@/api/auth'
import { useAuthStore } from '@/stores/auth'


const auth = useAuthStore()
const currentPassword = ref('')
const newPassword = ref('')
const confirmPassword = ref('')
const busy = ref(false)
const message = ref('')
const errorMessage = ref('')

const submit = async () => {
  message.value = ''
  errorMessage.value = ''
  if (newPassword.value !== confirmPassword.value) {
    errorMessage.value = '两次输入的新密码不一致'
    return
  }
  if (newPassword.value.length < 8 || newPassword.value.length > 128) {
    errorMessage.value = '新密码必须为 8 至 128 个字符'
    return
  }
  busy.value = true
  try {
    await auth.updatePassword(currentPassword.value, newPassword.value)
    currentPassword.value = ''
    newPassword.value = ''
    confirmPassword.value = ''
    message.value = '密码已更新，其他登录会话已退出'
  } catch (error) {
    errorMessage.value = apiErrorMessage(error)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <main class="password-page">
    <form class="password-card" @submit.prevent="submit">
      <h1>修改密码</h1>
      <p>新密码需为 8 至 128 个字符。更新后，其他设备会退出登录。</p>
      <label>
        当前密码
        <input
          v-model="currentPassword"
          data-testid="current-password"
          type="password"
          autocomplete="current-password"
          maxlength="128"
        >
      </label>
      <label>
        新密码
        <input
          v-model="newPassword"
          data-testid="new-password"
          type="password"
          autocomplete="new-password"
          minlength="8"
          maxlength="128"
        >
      </label>
      <label>
        确认新密码
        <input
          v-model="confirmPassword"
          data-testid="confirm-password"
          type="password"
          autocomplete="new-password"
          minlength="8"
          maxlength="128"
        >
      </label>
      <button type="submit" :disabled="busy">更新密码</button>
      <p v-if="message" class="success" role="status">{{ message }}</p>
      <p v-if="errorMessage" class="error" role="alert">{{ errorMessage }}</p>
    </form>
  </main>
</template>

<style scoped>
.password-page { min-height: calc(100vh - 48px); display: grid; place-items: center; padding: 24px; background: #f3f6fb; }
.password-card { width: min(440px, 100%); display: grid; gap: 16px; padding: 32px; background: white; border-radius: 14px; box-shadow: 0 16px 45px rgb(30 50 80 / 10%); }
h1, p { margin: 0; }
label { display: grid; gap: 7px; color: #344054; font-weight: 600; }
input { width: 100%; padding: 11px 12px; border: 1px solid #cbd5e1; border-radius: 8px; font: inherit; }
button { padding: 11px 16px; border: 0; border-radius: 8px; color: white; background: #315fc5; font: inherit; font-weight: 700; cursor: pointer; }
button:disabled { opacity: .5; cursor: default; }
.success { color: #067647; }
.error { color: #b42318; }
</style>
