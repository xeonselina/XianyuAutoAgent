<template>
  <main class="platform-page">
    <el-card class="platform-card" shadow="never">
      <template #header>
        <div>
          <p class="eyebrow">InventoryManager Platform</p>
          <h1>平台管理员登录</h1>
          <p class="subtitle">平台身份与租户手机号登录完全独立。</p>
        </div>
      </template>

      <el-form label-position="top" @submit.prevent="submitLogin">
        <el-form-item label="用户名">
          <el-input
            v-model="username"
            autocomplete="username"
            maxlength="128"
            @keyup.enter="submitLogin"
          />
        </el-form-item>
        <el-form-item label="密码">
          <el-input
            v-model="password"
            type="password"
            show-password
            autocomplete="current-password"
            @keyup.enter="submitLogin"
          />
        </el-form-item>
        <el-form-item label="第二因子">
          <el-radio-group v-model="factorMethod">
            <el-radio-button value="totp">验证器动态码</el-radio-button>
            <el-radio-button value="recovery_code">恢复码</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item :label="factorMethod === 'totp' ? '6 位动态码' : '一次性恢复码'">
          <el-input
            v-model="factor"
            :type="factorMethod === 'recovery_code' ? 'password' : 'text'"
            :show-password="factorMethod === 'recovery_code'"
            :maxlength="factorMethod === 'totp' ? 6 : 128"
            :inputmode="factorMethod === 'totp' ? 'numeric' : 'text'"
            autocomplete="one-time-code"
            @keyup.enter="submitLogin"
          />
        </el-form-item>
        <el-button
          class="submit-button"
          type="primary"
          :loading="submitting"
          :disabled="!canSubmit"
          @click="submitLogin"
        >登录平台</el-button>
      </el-form>

      <el-divider />
      <el-button link type="primary" @click="router.push({ name: 'platform-setup' })">
        使用主机命令签发的一次性 setup token
      </el-button>
    </el-card>
  </main>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useRouter } from 'vue-router'

import {
  loginPlatformAdmin,
  type PlatformFactorMethod,
} from '@/api/platformIdentity'

const router = useRouter()
const username = ref('')
const password = ref('')
const factorMethod = ref<PlatformFactorMethod>('totp')
const factor = ref('')
const submitting = ref(false)

const canSubmit = computed(() => (
  username.value.trim().length > 0
  && password.value.length > 0
  && factor.value.trim().length > 0
  && !submitting.value
))

const clearCredentials = () => {
  password.value = ''
  factor.value = ''
}

const submitLogin = async () => {
  if (!canSubmit.value) return
  submitting.value = true
  try {
    await loginPlatformAdmin({
      username: username.value,
      password: password.value,
      factor_method: factorMethod.value,
      factor: factor.value,
      device_name: '桌面浏览器',
    })
    clearCredentials()
    await router.replace({ name: 'platform-security' })
  } catch (error) {
    clearCredentials()
    ElMessage.error((error as Error).message)
  } finally {
    submitting.value = false
  }
}

onBeforeUnmount(clearCredentials)
</script>

<style scoped>
.platform-page { min-height: 100vh; display: grid; place-items: center; padding: 24px; background: #111827; }
.platform-card { width: min(460px, 100%); }
.eyebrow { margin: 0 0 6px; color: #409eff; font-size: 12px; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; }
h1 { margin: 0 0 8px; }
.subtitle { margin: 0; color: #606266; }
.submit-button { width: 100%; margin-top: 8px; }
</style>
