<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { apiErrorMessage } from '@/api/auth'
import { navigateAfterTenantLogin } from '@/router'
import { useAuthStore } from '@/stores/auth'


const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const phone = ref('')
const code = ref('')
const codeRequested = ref(false)
const busy = ref(false)
const message = ref('')
const errorMessage = ref('')

const requestCode = async () => {
  errorMessage.value = ''
  busy.value = true
  try {
    await auth.requestCode(phone.value)
    codeRequested.value = true
    message.value = '如果该手机号可登录，验证码将发送至手机'
  } catch (error) {
    errorMessage.value = apiErrorMessage(error)
  } finally {
    busy.value = false
  }
}

const login = async () => {
  errorMessage.value = ''
  busy.value = true
  try {
    if (!await auth.verifyCode(phone.value, code.value)) return
    await navigateAfterTenantLogin(
      route.query.next,
      (next) => router.replace(next),
      (next) => window.location.replace(next),
    )
  } catch (error) {
    errorMessage.value = apiErrorMessage(error)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <main class="auth-page">
    <form class="auth-card" @submit.prevent="login">
      <p class="eyebrow">租赁库存管理</p>
      <h1>短信验证码登录</h1>
      <label>
        手机号
        <input
          v-model.trim="phone"
          data-testid="phone"
          inputmode="tel"
          autocomplete="tel"
          maxlength="11"
          placeholder="请输入大陆手机号"
        >
      </label>
      <button
        data-testid="request-code"
        type="button"
        :disabled="busy || phone.length !== 11"
        @click="requestCode"
      >
        获取验证码
      </button>
      <label v-if="codeRequested">
        验证码
        <input
          v-model.trim="code"
          data-testid="code"
          inputmode="numeric"
          autocomplete="one-time-code"
          maxlength="6"
          placeholder="6 位验证码"
        >
      </label>
      <button
        v-if="codeRequested"
        data-testid="login"
        type="submit"
        :disabled="busy || code.length !== 6"
      >
        登录
      </button>
      <p v-if="message" class="hint">{{ message }}</p>
      <p v-if="errorMessage" class="error" role="alert">{{ errorMessage }}</p>
    </form>
  </main>
</template>

<style scoped>
.auth-page { min-height: 100vh; display: grid; place-items: center; padding: 24px; background: #f3f6fb; }
.auth-card { width: min(400px, 100%); display: grid; gap: 16px; padding: 32px; background: white; border-radius: 14px; box-shadow: 0 16px 45px rgb(30 50 80 / 10%); }
.eyebrow { margin: 0; color: #4967a8; font-weight: 700; }
h1 { margin: 0 0 8px; font-size: 26px; }
label { display: grid; gap: 7px; color: #344054; font-weight: 600; }
input { width: 100%; padding: 11px 12px; border: 1px solid #cbd5e1; border-radius: 8px; font: inherit; }
button { padding: 11px 16px; border: 0; border-radius: 8px; color: white; background: #315fc5; font: inherit; font-weight: 700; cursor: pointer; }
button:disabled { opacity: .5; cursor: default; }
.hint { margin: 0; color: #475467; }
.error { margin: 0; color: #b42318; }
</style>
