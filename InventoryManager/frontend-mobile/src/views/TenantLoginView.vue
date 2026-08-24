<template>
  <section class="login-view">
    <van-nav-bar title="手机号登录" />
    <div class="intro">
      <h1>登录库存管理</h1>
      <p>验证码由平台统一短信账号发送。</p>
    </div>
    <van-form @submit="verifyCode">
      <van-cell-group inset>
        <van-field
          v-model="phone"
          label="+86"
          type="tel"
          maxlength="11"
          placeholder="中国大陆手机号"
        />
        <van-field
          v-model="code"
          label="验证码"
          type="digit"
          maxlength="6"
          placeholder="6 位短信验证码"
        >
          <template #button>
            <van-button
              size="small"
              type="primary"
              native-type="button"
              :loading="sending"
              :disabled="!canSend || countdown > 0"
              @click="sendCode"
            >{{ countdown > 0 ? `${countdown} 秒` : '发送验证码' }}</van-button>
          </template>
        </van-field>
      </van-cell-group>
      <p v-if="challengeId" class="safe-message">
        如该号码可登录，验证码将由平台短信发送。
      </p>
      <div class="actions">
        <van-button
          block
          round
          type="primary"
          native-type="submit"
          :loading="verifying"
          :disabled="!canVerify"
        >登录</van-button>
      </div>
    </van-form>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import { showFailToast, showSuccessToast } from 'vant'
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
    showSuccessToast('验证码请求已提交')
  } catch (error) {
    showFailToast((error as Error).message)
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
      device_name: '移动浏览器',
    })
    await router.replace({
      name: result.effective_gate === 'active' ? 'gantt' : 'tenant-status',
    })
  } catch (error) {
    showFailToast((error as Error).message)
  } finally {
    verifying.value = false
  }
}

onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
})
</script>

<style scoped>
.login-view { min-height: 100%; overflow-y: auto; background: #f7f8fa; }
.intro { padding: 40px 24px 20px; }
.intro h1 { margin: 0 0 8px; font-size: 24px; }
.intro p, .safe-message { color: #646566; font-size: 14px; }
.safe-message { margin: 16px 24px 0; line-height: 1.5; }
.actions { padding: 28px 16px calc(28px + env(safe-area-inset-bottom)); }
</style>
