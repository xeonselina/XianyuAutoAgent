<template>
  <main class="security-page">
    <el-card shadow="never" v-loading="loading">
      <template #header>
        <div class="security-header">
          <div>
            <p class="eyebrow">Platform administrator</p>
            <h1>平台账号安全</h1>
            <p v-if="sessionStatus">{{ sessionStatus.username }} · {{ sessionStatus.mfa_method }}</p>
          </div>
          <el-button :loading="loggingOut" @click="logoutCurrent">退出当前设备</el-button>
          <el-button type="primary" plain @click="router.push({ name: 'platform-tenants' })">
            租户目录
          </el-button>
        </div>
      </template>

      <el-alert
        title="列表只显示本人平台会话；不会显示 bearer、摘要或来源 IP。"
        type="info"
        :closable="false"
      />

      <section class="step-up-panel">
        <div>
          <strong>刷新近期第二因子证明</strong>
          <p>D52 暂停/恢复和 D58 单租户审核会要求近期验证。成功后当前平台会话将安全轮换。</p>
        </div>
        <el-radio-group v-model="stepUpMethod" size="small">
          <el-radio-button value="totp">动态码</el-radio-button>
          <el-radio-button value="recovery_code">恢复码</el-radio-button>
        </el-radio-group>
        <el-input
          v-model="stepUpFactor"
          :type="stepUpMethod === 'recovery_code' ? 'password' : 'text'"
          :show-password="stepUpMethod === 'recovery_code'"
          :maxlength="stepUpMethod === 'totp' ? 6 : 128"
          :inputmode="stepUpMethod === 'totp' ? 'numeric' : 'text'"
          autocomplete="one-time-code"
          placeholder="输入当前因子"
          @keyup.enter="refreshRecentMfa"
        />
        <el-button
          type="primary"
          plain
          :loading="steppingUp"
          :disabled="!stepUpFactor.trim()"
          @click="refreshRecentMfa"
        >重新验证</el-button>
      </section>

      <section class="factor-panel">
        <div class="factor-heading">
          <div>
            <strong>平台第二因子</strong>
            <p>替换动态码前旧凭证保持有效；恢复码每次重新生成都会立即作废旧集合。</p>
          </div>
          <el-radio-group v-model="factorMethod" size="small" :disabled="factorSessionRevoked">
            <el-radio-button value="totp">动态码</el-radio-button>
            <el-radio-button value="recovery_code">恢复码</el-radio-button>
          </el-radio-group>
        </div>
        <div v-if="!factorSessionRevoked" class="factor-actions">
          <el-input
            v-model="factorValue"
            :type="factorMethod === 'recovery_code' ? 'password' : 'text'"
            :show-password="factorMethod === 'recovery_code'"
            :maxlength="factorMethod === 'totp' ? 6 : 128"
            autocomplete="one-time-code"
            placeholder="输入当前因子"
          />
          <el-button
            plain
            :loading="factorWorking === 'recovery'"
            :disabled="!factorValue.trim() || factorWorking !== null"
            @click="regenerateRecoveryCodes"
          >重新生成恢复码</el-button>
          <el-button
            type="primary"
            plain
            :loading="factorWorking === 'totp-start'"
            :disabled="!factorValue.trim() || factorWorking !== null"
            @click="beginTotpReplacement"
          >替换动态码</el-button>
        </div>

        <div v-if="pendingTotp" class="pending-totp">
          <el-alert
            title="请先把新 seed 加入验证器；确认成功前旧动态码仍可使用。"
            type="warning"
            :closable="false"
          />
          <el-input :model-value="pendingTotp.base32_seed" readonly />
          <div class="factor-actions">
            <el-input
              v-model="replacementTotpCode"
              maxlength="6"
              inputmode="numeric"
              autocomplete="one-time-code"
              placeholder="输入新验证器的 6 位动态码"
              @keyup.enter="completeTotpReplacement"
            />
            <el-button
              type="primary"
              :loading="factorWorking === 'totp-complete'"
              :disabled="!replacementTotpCode.trim() || factorWorking !== null"
              @click="completeTotpReplacement"
            >确认并替换</el-button>
          </div>
        </div>

        <div v-if="displayedRecoveryCodes.length" class="recovery-codes">
          <el-alert
            :title="factorSessionRevoked ? '动态码已替换，全部旧平台会话已撤销。请保存以下新恢复码后重新登录。' : '以下恢复码只展示这一次，请立即保存。'"
            type="success"
            :closable="false"
          />
          <code v-for="code in displayedRecoveryCodes" :key="code">{{ code }}</code>
          <el-button v-if="factorSessionRevoked" type="primary" @click="finishLogout">
            我已保存，返回登录
          </el-button>
        </div>
      </section>

      <el-table :data="sessions" class="session-table" empty-text="暂无有效平台会话">
        <el-table-column label="设备" min-width="210">
          <template #default="scope">
            {{ scope.row.device_name || '未命名浏览器' }}
            <el-tag v-if="scope.row.current" size="small" type="success">当前</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="mfa_method" label="登录因子" min-width="130" />
        <el-table-column label="最近活动" min-width="180">
          <template #default="scope">{{ formatTime(scope.row.last_seen_at) }}</template>
        </el-table-column>
        <el-table-column label="绝对到期" min-width="180">
          <template #default="scope">{{ formatTime(scope.row.absolute_expires_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="130" align="right">
          <template #default="scope">
            <el-button
              link
              type="danger"
              :loading="workingSessionId === scope.row.session_id"
              @click="revokeOne(scope.row)"
            >{{ scope.row.current ? '退出' : '撤销' }}</el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="danger-zone">
        <div>
          <strong>撤销全部平台会话</strong>
          <p>提交后当前设备和所有已复制的旧 Cookie 都会失效。</p>
        </div>
        <el-button type="danger" plain :loading="revokingAll" @click="revokeAll">
          全部退出
        </el-button>
      </div>
    </el-card>
  </main>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useRouter } from 'vue-router'

import {
  beginPlatformTotpReplacement,
  clearPlatformCsrfToken,
  completePlatformTotpReplacement as submitPlatformTotpReplacement,
  getPlatformSessionStatus,
  listPlatformSessions,
  logoutPlatformSession,
  revokeAllPlatformSessions,
  revokePlatformSession,
  regeneratePlatformRecoveryCodes,
  stepUpPlatformSession,
  type PlatformFactorMethod,
  type PlatformSessionDevice,
  type PlatformSessionStatus,
} from '@/api/platformIdentity'

const router = useRouter()
const loading = ref(false)
const loggingOut = ref(false)
const revokingAll = ref(false)
const workingSessionId = ref<string | null>(null)
const steppingUp = ref(false)
const stepUpMethod = ref<PlatformFactorMethod>('totp')
const stepUpFactor = ref('')
const factorMethod = ref<PlatformFactorMethod>('totp')
const factorValue = ref('')
const factorWorking = ref<'recovery' | 'totp-start' | 'totp-complete' | null>(null)
const pendingTotp = ref<{ credential_id: string; base32_seed: string } | null>(null)
const replacementTotpCode = ref('')
const displayedRecoveryCodes = ref<string[]>([])
const factorSessionRevoked = ref(false)
const sessionStatus = ref<PlatformSessionStatus | null>(null)
const sessions = ref<PlatformSessionDevice[]>([])

const formatTime = (value: string) => new Intl.DateTimeFormat('zh-CN', {
  dateStyle: 'medium',
  timeStyle: 'short',
}).format(new Date(value))

const finishLogout = async () => {
  clearPlatformCsrfToken()
  await router.replace({ name: 'platform-login' })
}

const load = async () => {
  loading.value = true
  try {
    const [status, activeSessions] = await Promise.all([
      getPlatformSessionStatus(),
      listPlatformSessions(),
    ])
    sessionStatus.value = status
    sessions.value = activeSessions
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    loading.value = false
  }
}

const refreshRecentMfa = async () => {
  if (!stepUpFactor.value.trim() || steppingUp.value) return
  steppingUp.value = true
  try {
    await stepUpPlatformSession({
      factor_method: stepUpMethod.value,
      factor: stepUpFactor.value,
    })
    stepUpFactor.value = ''
    await load()
    ElMessage.success('近期第二因子证明已刷新，会话已轮换')
  } catch (error) {
    stepUpFactor.value = ''
    ElMessage.error((error as Error).message)
  } finally {
    steppingUp.value = false
  }
}

const currentFactorPayload = () => ({
  factor_method: factorMethod.value,
  factor: factorValue.value,
})

const regenerateRecoveryCodes = async () => {
  if (!factorValue.value.trim() || factorWorking.value) return
  factorWorking.value = 'recovery'
  try {
    const result = await regeneratePlatformRecoveryCodes(currentFactorPayload())
    displayedRecoveryCodes.value = [...result.recovery_codes]
    factorValue.value = ''
    ElMessage.success('旧恢复码已作废，新恢复码只展示一次')
  } catch (error) {
    factorValue.value = ''
    ElMessage.error((error as Error).message)
  } finally {
    factorWorking.value = null
  }
}

const beginTotpReplacement = async () => {
  if (!factorValue.value.trim() || factorWorking.value) return
  factorWorking.value = 'totp-start'
  try {
    pendingTotp.value = await beginPlatformTotpReplacement(currentFactorPayload())
    factorValue.value = ''
    replacementTotpCode.value = ''
    ElMessage.success('新动态码已暂存，旧动态码仍然有效')
  } catch (error) {
    factorValue.value = ''
    ElMessage.error((error as Error).message)
  } finally {
    factorWorking.value = null
  }
}

const completeTotpReplacement = async () => {
  if (!pendingTotp.value || !replacementTotpCode.value.trim() || factorWorking.value) return
  factorWorking.value = 'totp-complete'
  try {
    const result = await submitPlatformTotpReplacement(
      pendingTotp.value.credential_id,
      replacementTotpCode.value,
    )
    displayedRecoveryCodes.value = [...result.recovery_codes]
    factorSessionRevoked.value = true
    pendingTotp.value = null
    sessions.value = []
    sessionStatus.value = null
    replacementTotpCode.value = ''
  } catch (error) {
    replacementTotpCode.value = ''
    ElMessage.error((error as Error).message)
  } finally {
    factorWorking.value = null
  }
}

const logoutCurrent = async () => {
  loggingOut.value = true
  try {
    await logoutPlatformSession()
    await finishLogout()
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    loggingOut.value = false
  }
}

const revokeOne = async (target: PlatformSessionDevice) => {
  try {
    await ElMessageBox.confirm(
      target.current ? '确认退出当前平台会话？' : `确认撤销“${target.device_name || '未命名浏览器'}”？`,
      '平台账号安全确认',
      { type: 'warning', confirmButtonText: '确认', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  workingSessionId.value = target.session_id
  try {
    const result = await revokePlatformSession(target.session_id)
    if (result.current_session_revoked) {
      await finishLogout()
      return
    }
    sessions.value = sessions.value.filter(item => item.session_id !== target.session_id)
    ElMessage.success('平台会话已撤销')
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    workingSessionId.value = null
  }
}

const revokeAll = async () => {
  try {
    await ElMessageBox.confirm(
      '确认撤销包括当前设备在内的全部平台会话？',
      '撤销全部平台会话',
      { type: 'warning', confirmButtonText: '全部撤销', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  revokingAll.value = true
  try {
    await revokeAllPlatformSessions()
    await finishLogout()
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    revokingAll.value = false
  }
}

onMounted(load)
onBeforeUnmount(() => {
  factorValue.value = ''
  replacementTotpCode.value = ''
  pendingTotp.value = null
  displayedRecoveryCodes.value = []
})
</script>

<style scoped>
.security-page { min-height: 100vh; padding: 32px; background: #111827; }
.security-page > .el-card { max-width: 1040px; margin: 0 auto; }
.security-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 24px; }
.eyebrow { margin: 0 0 6px; color: #409eff; font-size: 12px; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; }
.security-header h1 { margin: 0 0 8px; }
.security-header p:not(.eyebrow), .danger-zone p { margin: 0; color: #606266; }
.session-table { margin-top: 20px; }
.step-up-panel { display: grid; grid-template-columns: minmax(240px, 1fr) auto minmax(180px, 280px) auto; align-items: end; gap: 16px; margin-top: 20px; padding: 18px; border: 1px solid #dcdfe6; border-radius: 8px; }
.step-up-panel p { margin: 6px 0 0; color: #606266; }
.factor-panel { display: grid; gap: 16px; margin-top: 20px; padding: 18px; border: 1px solid #dcdfe6; border-radius: 8px; }
.factor-heading { display: flex; align-items: start; justify-content: space-between; gap: 16px; }
.factor-heading p { margin: 6px 0 0; color: #606266; }
.factor-actions { display: flex; align-items: center; gap: 12px; }
.pending-totp, .recovery-codes { display: grid; gap: 12px; }
.recovery-codes code { display: block; padding: 8px 10px; border-radius: 4px; background: #f5f7fa; }
.danger-zone { display: flex; justify-content: space-between; align-items: center; gap: 24px; margin-top: 24px; padding: 20px; border: 1px solid #f3d1d1; border-radius: 8px; background: #fef0f0; }
.danger-zone p { margin-top: 6px; }
@media (max-width: 820px) { .step-up-panel { grid-template-columns: 1fr; align-items: stretch; } .factor-heading, .factor-actions { align-items: stretch; flex-direction: column; } }
</style>
