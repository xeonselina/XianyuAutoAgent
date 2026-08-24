<template>
  <main class="login-page">
    <el-card class="login-card" shadow="never">
      <template #header>
        <div>
          <h1>手机号登录</h1>
          <p>验证码由平台统一短信账号发送。</p>
        </div>
      </template>
      <el-form label-position="top" @submit.prevent>
        <el-form-item label="中国大陆手机号">
          <el-input v-model="phone" maxlength="11" inputmode="numeric">
            <template #prepend>+86</template>
          </el-input>
        </el-form-item>
        <el-form-item label="短信验证码">
          <div class="code-row">
            <el-input v-model="code" maxlength="6" inputmode="numeric" />
            <el-button
              :loading="sending"
              :disabled="!canSend || countdown > 0"
              @click="sendCode"
            >{{ countdown > 0 ? `${countdown} 秒` : '发送验证码' }}</el-button>
          </div>
        </el-form-item>
        <el-alert
          v-if="challengeId"
          type="info"
          :closable="false"
          title="如该号码可登录，验证码将由平台短信发送。"
        />
        <el-button
          class="login-button"
          type="primary"
          :loading="verifying"
          :disabled="!canVerify"
          @click="verifyCode"
        >登录</el-button>
      </el-form>
    </el-card>
  </main>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useRouter } from 'vue-router'

import {
  requestTenantLoginCode,
  verifyTenantLoginCode,
} from '@/api/tenantIdentity'

const router = useRouter()
const phone = ref('')
const code = ref('')
const challengeId = ref('')
const countdown = ref(0)
const sending = ref(false)
const verifying = ref(false)
let timer: ReturnType<typeof setInterval> | null = null

const canSend = computed(() => /^1\d{10}$/.test(phone.value))
const canVerify = computed(() => (
  canSend.value && /^\d{6}$/.test(code.value) && Boolean(challengeId.value)
))

const startCountdown = (seconds: number) => {
  countdown.value = Math.max(1, seconds)
  if (timer) clearInterval(timer)
  timer = setInterval(() => {
    countdown.value = Math.max(0, countdown.value - 1)
    if (countdown.value === 0 && timer) {
      clearInterval(timer)
      timer = null
    }
  }, 1000)
}

const sendCode = async () => {
  if (!canSend.value || sending.value) return
  sending.value = true
  try {
    const result = await requestTenantLoginCode(phone.value)
    challengeId.value = result.challenge_id
    code.value = ''
    startCountdown(result.resend_after_seconds)
    ElMessage.success('验证码请求已提交')
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    sending.value = false
  }
}

const verifyCode = async () => {
  if (!canVerify.value || verifying.value) return
  verifying.value = true
  try {
    const result = await verifyTenantLoginCode({
      phone: phone.value,
      challenge_id: challengeId.value,
      code: code.value,
      device_name: '桌面浏览器',
    })
    await router.replace({
      name: result.effective_gate === 'active' ? 'gantt' : 'tenant-status',
    })
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    verifying.value = false
  }
}

onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
})
</script>

<style scoped>
.login-page { min-height: 100vh; display: grid; place-items: center; padding: 24px; background: #f5f7fa; }
.login-card { width: min(440px, 100%); }
.login-card h1 { margin: 0 0 8px; }
.login-card p { margin: 0; color: #606266; }
.code-row { display: grid; grid-template-columns: 1fr 128px; gap: 12px; width: 100%; }
.login-button { width: 100%; margin-top: 20px; }
</style>
