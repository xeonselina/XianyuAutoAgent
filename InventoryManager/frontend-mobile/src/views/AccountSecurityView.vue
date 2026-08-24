<template>
  <section class="security-view">
    <van-nav-bar title="账号安全" left-arrow @click-left="router.back()" />
    <van-loading v-if="loading" class="loading" vertical>加载登录设备</van-loading>
    <template v-else>
      <div class="notice">设备表示一次浏览器登录。这里只显示本人设备摘要和活动时间。</div>
      <van-cell-group inset title="更换登录手机号" class="phone-change">
        <van-field
          v-model="newPhone"
          type="tel"
          maxlength="18"
          label="新手机号"
          placeholder="请输入 11 位手机号"
        />
        <van-cell title="旧号与新号必须分别验证；成功后全部设备退出。" />
        <van-field
          v-if="phoneChallenge"
          v-model="oldPhoneCode"
          type="digit"
          maxlength="6"
          label="旧号验证码"
        />
        <van-field
          v-if="phoneChallenge"
          v-model="newPhoneCode"
          type="digit"
          maxlength="6"
          label="新号验证码"
        />
        <div class="phone-actions">
          <van-button
            v-if="!phoneChallenge"
            block
            type="primary"
            :loading="requestingPhoneCodes"
            @click="requestPhoneCodes"
          >向两个号码发送验证码</van-button>
          <van-button
            v-else
            block
            type="primary"
            :loading="confirmingPhoneChange"
            @click="confirmPhoneChange"
          >确认更换并退出全部设备</van-button>
        </div>
      </van-cell-group>
      <van-empty v-if="sessions.length === 0" description="暂无有效登录设备" />
      <van-cell-group v-else inset title="登录设备">
        <van-cell v-for="session in sessions" :key="session.session_id">
          <template #title>
            <span>{{ session.device_summary }}</span>
            <van-tag v-if="session.is_current" type="success" class="current-tag">当前设备</van-tag>
          </template>
          <template #label>
            <div>创建：{{ formatTime(session.created_at) }}</div>
            <div>最近活动：{{ formatTime(session.last_seen_at) }}</div>
          </template>
          <template #right-icon>
            <van-button
              size="small"
              type="danger"
              plain
              :loading="workingSessionId === session.session_id"
              @click="revokeOne(session)"
            >{{ session.is_current ? '退出' : '撤销' }}</van-button>
          </template>
        </van-cell>
      </van-cell-group>
      <div class="all-actions">
        <van-button block type="danger" plain :loading="revokingAll" @click="revokeAll">
          退出全部设备
        </van-button>
      </div>
    </template>
  </section>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { showConfirmDialog, showFailToast, showSuccessToast } from 'vant'
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
const loading = ref(true)
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
  dateStyle: 'short',
  timeStyle: 'short',
}).format(new Date(value))

const load = async () => {
  loading.value = true
  try {
    sessions.value = await listTenantSessions()
  } catch (error) {
    showFailToast((error as Error).message)
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
    await showConfirmDialog({
      title: '账号安全确认',
      message: session.is_current
        ? '确认退出当前设备？'
        : `确认撤销“${session.device_summary}”？`,
    })
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
    showSuccessToast('设备会话已撤销')
  } catch (error) {
    showFailToast((error as Error).message)
  } finally {
    workingSessionId.value = null
  }
}

const revokeAll = async () => {
  try {
    await showConfirmDialog({
      title: '退出全部设备',
      message: '确认退出包括当前设备在内的全部登录设备？',
    })
  } catch {
    return
  }
  revokingAll.value = true
  try {
    await revokeAllTenantSessions()
    await finishCurrentLogout()
  } catch (error) {
    showFailToast((error as Error).message)
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
    showSuccessToast('验证码已分别发送到旧号和新号')
  } catch (error) {
    showFailToast((error as Error).message)
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
    showSuccessToast('手机号已更换，请重新登录')
    await router.replace({ name: 'tenant-login' })
  } catch (error) {
    showFailToast((error as Error).message)
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
.security-view { min-height: 100%; overflow-y: auto; background: #f7f8fa; }
.loading { padding-top: 30vh; }
.notice { margin: 16px; padding: 12px; border-radius: 8px; color: #646566; background: #fffbe8; font-size: 13px; line-height: 1.5; }
.current-tag { margin-left: 8px; }
.phone-change { margin-top: 16px; }
.phone-actions { padding: 12px 16px 16px; }
.all-actions { padding: 24px 16px calc(24px + env(safe-area-inset-bottom)); }
</style>
