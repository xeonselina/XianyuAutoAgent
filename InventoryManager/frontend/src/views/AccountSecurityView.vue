<template>
  <main class="security-page">
    <el-card shadow="never" v-loading="loading">
      <template #header>
        <div class="security-header">
          <div>
            <h1>账号安全</h1>
            <p>这里的“设备”表示一次浏览器登录，不是硬件指纹。</p>
          </div>
          <el-button @click="router.back()">返回</el-button>
        </div>
      </template>

      <el-alert
        title="列表只显示本人设备摘要和活动时间，不显示登录令牌、摘要或 IP。"
        type="info"
        :closable="false"
      />

      <section class="phone-change">
        <h2>更换登录手机号</h2>
        <p>必须同时验证当前旧号码和新号码；成功后全部设备退出，并用新号码重新登录。</p>
        <el-form label-position="top" @submit.prevent>
          <el-form-item label="新手机号（中国大陆）">
            <el-input
              v-model="newPhone"
              maxlength="18"
              autocomplete="tel"
              placeholder="请输入 11 位手机号"
            />
          </el-form-item>
          <el-button :loading="requestingPhoneCodes" @click="requestPhoneCodes">
            {{ phoneChallenge ? '重新确认发码状态' : '向旧号和新号发送验证码' }}
          </el-button>
          <div v-if="phoneChallenge" class="phone-codes">
            <el-form-item label="旧手机号验证码">
              <el-input v-model="oldPhoneCode" maxlength="6" autocomplete="one-time-code" />
            </el-form-item>
            <el-form-item label="新手机号验证码">
              <el-input v-model="newPhoneCode" maxlength="6" autocomplete="one-time-code" />
            </el-form-item>
            <el-button
              type="primary"
              :loading="confirmingPhoneChange"
              @click="confirmPhoneChange"
            >确认更换并退出全部设备</el-button>
          </div>
        </el-form>
      </section>

      <el-table :data="sessions" class="session-table" empty-text="暂无有效登录设备">
        <el-table-column label="设备" min-width="220">
          <template #default="scope">
            {{ scope.row.device_summary }}
            <el-tag v-if="scope.row.is_current" size="small" type="success">当前设备</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="创建时间" min-width="180">
          <template #default="scope">{{ formatTime(scope.row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="最近活动" min-width="180">
          <template #default="scope">{{ formatTime(scope.row.last_seen_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="140" align="right">
          <template #default="scope">
            <el-button
              link
              type="danger"
              :loading="workingSessionId === scope.row.session_id"
              @click="revokeOne(scope.row)"
            >
              {{ scope.row.is_current ? '退出登录' : '撤销设备' }}
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="danger-zone">
        <div>
          <strong>退出全部设备</strong>
          <p>提交后所有已复制的旧 Cookie 也会立即失效。</p>
        </div>
        <el-button type="danger" plain :loading="revokingAll" @click="revokeAll">
          退出全部设备
        </el-button>
      </div>
    </el-card>
  </main>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useRouter } from 'vue-router'

import {
  clearTenantCsrfToken,
  confirmTenantPhoneChange,
  listTenantSessions,
  logoutCurrentSession,
  revokeAllTenantSessions,
  revokeTenantSession,
  requestTenantPhoneChange,
  type TenantPhoneChangeChallenge,
  type TenantSessionDevice,
} from '@/api/tenantIdentity'

const router = useRouter()
const loading = ref(false)
const revokingAll = ref(false)
const workingSessionId = ref<string | null>(null)
const sessions = ref<TenantSessionDevice[]>([])
const newPhone = ref('')
const oldPhoneCode = ref('')
const newPhoneCode = ref('')
const phoneActionId = ref<string | null>(null)
const phoneChallenge = ref<TenantPhoneChangeChallenge | null>(null)
const requestingPhoneCodes = ref(false)
const confirmingPhoneChange = ref(false)

const formatTime = (value: string) => new Intl.DateTimeFormat('zh-CN', {
  dateStyle: 'medium',
  timeStyle: 'short',
}).format(new Date(value))

const load = async () => {
  loading.value = true
  try {
    sessions.value = await listTenantSessions()
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    loading.value = false
  }
}

const finishCurrentLogout = async () => {
  clearTenantCsrfToken()
  await router.replace({ name: 'tenant-login' })
}

const revokeOne = async (session: TenantSessionDevice) => {
  try {
    await ElMessageBox.confirm(
      session.is_current ? '确认退出当前设备？' : `确认撤销“${session.device_summary}”？`,
      '账号安全确认',
      { type: 'warning', confirmButtonText: '确认', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  workingSessionId.value = session.session_id
  try {
    if (session.is_current) {
      await logoutCurrentSession()
      await finishCurrentLogout()
      return
    }
    await revokeTenantSession(session.session_id)
    sessions.value = sessions.value.filter(item => item.session_id !== session.session_id)
    ElMessage.success('设备会话已撤销')
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    workingSessionId.value = null
  }
}

const revokeAll = async () => {
  try {
    await ElMessageBox.confirm(
      '确认退出包括当前设备在内的全部登录设备？',
      '退出全部设备',
      { type: 'warning', confirmButtonText: '全部退出', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  revokingAll.value = true
  try {
    await revokeAllTenantSessions()
    await finishCurrentLogout()
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    revokingAll.value = false
  }
}

const clearPhoneProofs = () => {
  oldPhoneCode.value = ''
  newPhoneCode.value = ''
  phoneChallenge.value = null
  phoneActionId.value = null
}

const requestPhoneCodes = async () => {
  requestingPhoneCodes.value = true
  try {
    phoneActionId.value ||= crypto.randomUUID()
    phoneChallenge.value = await requestTenantPhoneChange(
      newPhone.value,
      phoneActionId.value,
    )
    ElMessage.success('验证码已分别发送到旧手机号和新手机号')
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    requestingPhoneCodes.value = false
  }
}

const confirmPhoneChange = async () => {
  if (!phoneActionId.value || !phoneChallenge.value) return
  confirmingPhoneChange.value = true
  try {
    await confirmTenantPhoneChange({
      new_phone: newPhone.value,
      action_id: phoneActionId.value,
      old_challenge_id: phoneChallenge.value.old_challenge_id,
      old_code: oldPhoneCode.value,
      new_challenge_id: phoneChallenge.value.new_challenge_id,
      new_code: newPhoneCode.value,
    })
    clearTenantCsrfToken()
    clearPhoneProofs()
    ElMessage.success('手机号已更换，请使用新号码重新登录')
    await router.replace({ name: 'tenant-login' })
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    confirmingPhoneChange.value = false
  }
}

watch(newPhone, (_next, previous) => {
  if (previous) clearPhoneProofs()
})

onMounted(load)
onBeforeUnmount(clearPhoneProofs)
</script>

<style scoped>
.security-page { min-height: 100vh; padding: 32px; background: #f5f7fa; }
.security-page > .el-card { max-width: 980px; margin: 0 auto; }
.security-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 24px; }
.security-header h1 { margin: 0 0 8px; }
.security-header p, .danger-zone p { margin: 0; color: #606266; }
.session-table { margin-top: 20px; }
.phone-change { margin-top: 24px; padding: 20px; border: 1px solid #d9ecff; border-radius: 8px; background: #f4faff; }
.phone-change h2 { margin: 0 0 8px; font-size: 18px; }
.phone-change p { margin: 0 0 16px; color: #606266; }
.phone-change .el-form { max-width: 520px; }
.phone-codes { display: grid; grid-template-columns: 1fr 1fr; gap: 0 16px; margin-top: 16px; }
.phone-codes .el-button { grid-column: 1 / -1; justify-self: start; }
.danger-zone { display: flex; justify-content: space-between; align-items: center; gap: 24px; margin-top: 24px; padding: 20px; border: 1px solid #f3d1d1; border-radius: 8px; background: #fef0f0; }
.danger-zone p { margin-top: 6px; }
</style>
