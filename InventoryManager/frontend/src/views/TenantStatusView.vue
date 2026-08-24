<template>
  <main class="status-page">
    <el-card class="status-card" shadow="never" v-loading="loading">
      <template #header><h1>{{ title }}</h1></template>
      <p>{{ description }}</p>
      <template v-if="status?.effective_gate === 'expired' && subscription">
        <el-alert
          type="warning"
          :closable="false"
          :title="`当前服务期至 ${formattedExpiry}；Operator 只能查看和退出。`"
        />
        <el-form
          v-if="subscription.can_redeem"
          class="renewal-form"
          label-position="top"
          @submit.prevent="redeem"
        >
          <el-form-item label="续期兑换码">
            <el-input
              v-model="redemptionCode"
              autocomplete="off"
              maxlength="64"
              placeholder="输入平台提供的兑换码"
              @keyup.enter="redeem"
            />
          </el-form-item>
          <el-button
            type="primary"
            :loading="renewing"
            :disabled="!redemptionCode.trim()"
            @click="redeem"
          >确认续期</el-button>
        </el-form>
      </template>
      <div class="actions">
        <el-button
          v-if="canOpenSecurity"
          @click="router.push({ name: 'account-security' })"
        >账号安全</el-button>
        <el-button type="danger" plain :loading="loggingOut" @click="logout">
          退出登录
        </el-button>
      </div>
    </el-card>
  </main>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useRouter } from 'vue-router'

import {
  clearTenantCsrfToken,
  getTenantSessionStatus,
  logoutCurrentSession,
  type TenantSessionStatus,
} from '@/api/tenantIdentity'
import {
  getTenantSubscriptionStatus,
  redeemTenantSubscription,
  type TenantSubscriptionStatus,
} from '@/api/tenantSubscription'

const router = useRouter()
const loading = ref(true)
const loggingOut = ref(false)
const renewing = ref(false)
const status = ref<TenantSessionStatus | null>(null)
const subscription = ref<TenantSubscriptionStatus | null>(null)
const redemptionCode = ref('')
const renewalIdempotencyKey = ref<string | null>(null)

const title = computed(() => status.value?.effective_gate === 'suspended'
  ? '租户已暂停'
  : '服务期已到期')
const description = computed(() => status.value?.effective_gate === 'suspended'
  ? '业务、后台任务和第三方操作保持关闭，请联系平台处理。'
  : '当前只能查看到期状态并退出；Admin 后续可在本页提交兑换码续期。')
const canOpenSecurity = computed(() => (
  status.value?.effective_gate === 'suspended' && status.value.role === 'admin'
))
const formattedExpiry = computed(() => subscription.value
  ? new Date(subscription.value.expires_at).toLocaleString('zh-CN')
  : '')

const load = async () => {
  loading.value = true
  try {
    status.value = await getTenantSessionStatus()
    if (status.value.effective_gate === 'active') {
      await router.replace({ name: 'gantt' })
      return
    }
    if (status.value.effective_gate === 'expired') {
      subscription.value = await getTenantSubscriptionStatus()
    }
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    loading.value = false
  }
}

const redeem = async () => {
  if (
    renewing.value
    || !subscription.value?.can_redeem
    || !redemptionCode.value.trim()
  ) return
  renewing.value = true
  try {
    renewalIdempotencyKey.value ??=
      `subscription-renewal:${crypto.randomUUID()}`
    await redeemTenantSubscription({
      code: redemptionCode.value,
      idempotency_key: renewalIdempotencyKey.value,
      expected_subscription_row_version:
        subscription.value.subscription_row_version,
    })
    redemptionCode.value = ''
    const refreshed = await getTenantSessionStatus()
    status.value = refreshed
    if (refreshed.effective_gate !== 'active') {
      throw new Error('续期状态尚未生效，请刷新后重试')
    }
    renewalIdempotencyKey.value = null
    await router.replace({ name: 'gantt' })
  } catch (error) {
    try {
      const refreshed = await getTenantSessionStatus()
      status.value = refreshed
      if (refreshed.effective_gate === 'active') {
        redemptionCode.value = ''
        renewalIdempotencyKey.value = null
        await router.replace({ name: 'gantt' })
        return
      }
      subscription.value = await getTenantSubscriptionStatus()
      renewalIdempotencyKey.value = null
    } catch {
      // Keep the same idempotency key when authority cannot be reread.
    }
    ElMessage.error((error as Error).message)
  } finally {
    renewing.value = false
  }
}

const logout = async () => {
  loggingOut.value = true
  try {
    await logoutCurrentSession()
    clearTenantCsrfToken()
    await router.replace({ name: 'tenant-login' })
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    loggingOut.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.status-page { min-height: 100vh; display: grid; place-items: center; padding: 24px; background: #f5f7fa; }
.status-card { width: min(620px, 100%); }
.status-card h1 { margin: 0; }
.status-card p { color: #606266; line-height: 1.7; }
.actions { display: flex; justify-content: flex-end; gap: 12px; margin-top: 24px; }
.renewal-form { margin-top: 20px; padding: 16px; border-radius: 8px; background: #f8f9fb; }
</style>
