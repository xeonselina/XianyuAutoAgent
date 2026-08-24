<template>
  <main class="setup-page">
    <el-card class="setup-card" shadow="never">
      <template #header>
        <div class="setup-header">
          <div>
            <p class="eyebrow">Host-authorized setup</p>
            <h1>平台管理员初始化</h1>
            <p>所有凭证只保留在当前页面内存，不会写入浏览器持久存储。</p>
          </div>
          <el-tag type="info">{{ stepLabel }}</el-tag>
        </div>
      </template>

      <el-alert
        v-if="step !== 'recovery'"
        title="请勿刷新或关闭页面。setup token 只能由主机命令创建，完成后立即失效。"
        type="warning"
        :closable="false"
        show-icon
      />

      <section v-if="step === 'token'" class="step-content">
        <h2>1. 验证一次性 setup token</h2>
        <el-input
          v-model="setupToken"
          type="password"
          show-password
          autocomplete="off"
          placeholder="粘贴主机命令输出的 setup token"
          @keyup.enter="consumeToken"
        />
        <el-button
          type="primary"
          :loading="working"
          :disabled="!setupToken.trim()"
          @click="consumeToken"
        >继续</el-button>
      </section>

      <section v-else-if="step === 'password'" class="step-content">
        <h2>2. 设置平台密码</h2>
        <el-form label-position="top" @submit.prevent="savePassword">
          <el-form-item label="新密码">
            <el-input
              v-model="password"
              type="password"
              show-password
              autocomplete="new-password"
            />
          </el-form-item>
          <el-form-item label="再次输入">
            <el-input
              v-model="passwordConfirmation"
              type="password"
              show-password
              autocomplete="new-password"
              @keyup.enter="savePassword"
            />
          </el-form-item>
          <el-button
            type="primary"
            :loading="working"
            :disabled="!canSavePassword"
            @click="savePassword"
          >保存密码并创建 TOTP</el-button>
        </el-form>
      </section>

      <section v-else-if="step === 'totp'" class="step-content">
        <h2>3. 绑定验证器</h2>
        <p>在验证器应用中选择“手动输入密钥”，录入以下 Base32 密钥：</p>
        <div class="secret-box" data-sensitive="totp-seed">
          <code>{{ base32Seed }}</code>
        </div>
        <el-alert
          title="该密钥只显示这一次。确认动态码前请完成验证器录入。"
          type="info"
          :closable="false"
        />
        <el-form label-position="top" @submit.prevent="finishSetup">
          <el-form-item label="当前 6 位动态码">
            <el-input
              v-model="totpCode"
              maxlength="6"
              inputmode="numeric"
              autocomplete="one-time-code"
              @keyup.enter="finishSetup"
            />
          </el-form-item>
          <el-button
            type="primary"
            :loading="working"
            :disabled="totpCode.trim().length !== 6"
            @click="finishSetup"
          >确认并生成恢复码</el-button>
        </el-form>
      </section>

      <section v-else class="step-content">
        <h2>4. 离线保存恢复码</h2>
        <el-alert
          title="这是恢复码唯一一次显示。每个恢复码只能使用一次；请现在保存到离线安全位置。"
          type="success"
          :closable="false"
          show-icon
        />
        <div class="recovery-grid" data-sensitive="recovery-codes">
          <code v-for="code in recoveryCodes" :key="code">{{ code }}</code>
        </div>
        <el-checkbox v-model="recoveryAcknowledged">
          我已将全部恢复码保存到离线安全位置
        </el-checkbox>
        <el-button
          type="primary"
          :disabled="!recoveryAcknowledged"
          @click="goToLogin"
        >清除页面并前往登录</el-button>
      </section>
    </el-card>
  </main>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useRouter } from 'vue-router'

import {
  beginPlatformTotpSetup,
  completePlatformSetup,
  consumePlatformSetupToken,
  setPlatformSetupPassword,
} from '@/api/platformIdentity'

type SetupStep = 'token' | 'password' | 'totp' | 'recovery'

const router = useRouter()
const step = ref<SetupStep>('token')
const setupToken = ref('')
const password = ref('')
const passwordConfirmation = ref('')
const credentialId = ref('')
const base32Seed = ref('')
const totpCode = ref('')
const recoveryCodes = ref<string[]>([])
const recoveryAcknowledged = ref(false)
const working = ref(false)

const stepLabel = computed(() => ({
  token: '1 / 4',
  password: '2 / 4',
  totp: '3 / 4',
  recovery: '4 / 4',
})[step.value])

const canSavePassword = computed(() => (
  password.value.length > 0
  && password.value === passwordConfirmation.value
  && !working.value
))

const clearPassword = () => {
  password.value = ''
  passwordConfirmation.value = ''
}

const clearSensitiveState = () => {
  setupToken.value = ''
  clearPassword()
  credentialId.value = ''
  base32Seed.value = ''
  totpCode.value = ''
  recoveryCodes.value = []
}

const consumeToken = async () => {
  if (!setupToken.value.trim() || working.value) return
  working.value = true
  try {
    await consumePlatformSetupToken(setupToken.value)
    step.value = 'password'
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    working.value = false
  }
}

const savePassword = async () => {
  if (!canSavePassword.value) return
  working.value = true
  try {
    await setPlatformSetupPassword(setupToken.value, password.value)
    clearPassword()
    const totp = await beginPlatformTotpSetup(setupToken.value)
    credentialId.value = totp.credential_id
    base32Seed.value = totp.base32_seed
    step.value = 'totp'
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    working.value = false
  }
}

const finishSetup = async () => {
  if (totpCode.value.trim().length !== 6 || working.value) return
  working.value = true
  try {
    const result = await completePlatformSetup(
      setupToken.value,
      credentialId.value,
      totpCode.value,
    )
    setupToken.value = ''
    credentialId.value = ''
    base32Seed.value = ''
    totpCode.value = ''
    recoveryCodes.value = [...result.recovery_codes]
    step.value = 'recovery'
  } catch (error) {
    totpCode.value = ''
    ElMessage.error((error as Error).message)
  } finally {
    working.value = false
  }
}

const goToLogin = async () => {
  if (!recoveryAcknowledged.value) return
  clearSensitiveState()
  await router.replace({ name: 'platform-login' })
}

onBeforeUnmount(clearSensitiveState)
</script>

<style scoped>
.setup-page { min-height: 100vh; display: grid; place-items: center; padding: 28px; background: #111827; }
.setup-card { width: min(680px, 100%); }
.setup-header { display: flex; justify-content: space-between; gap: 24px; align-items: flex-start; }
.eyebrow { margin: 0 0 6px; color: #409eff; font-size: 12px; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; }
h1 { margin: 0 0 8px; }
.setup-header p:not(.eyebrow) { margin: 0; color: #606266; }
.step-content { display: grid; gap: 18px; margin-top: 24px; }
.step-content h2, .step-content p { margin: 0; }
.secret-box, .recovery-grid { padding: 16px; border: 1px solid #dcdfe6; border-radius: 8px; background: #f5f7fa; }
.secret-box code { overflow-wrap: anywhere; font-size: 16px; letter-spacing: .08em; }
.recovery-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px 24px; }
.recovery-grid code { overflow-wrap: anywhere; }
@media (max-width: 560px) { .recovery-grid { grid-template-columns: 1fr; } }
</style>
