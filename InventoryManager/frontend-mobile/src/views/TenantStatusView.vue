<template>
  <section class="status-view">
    <van-nav-bar :title="title" />
    <van-loading v-if="loading" class="loading" vertical>读取租户状态</van-loading>
    <template v-else>
      <div class="status-card">
        <van-icon :name="status?.effective_gate === 'suspended' ? 'pause-circle-o' : 'clock-o'" size="52" color="#ee0a24" />
        <h1>{{ title }}</h1>
        <p>{{ description }}</p>
        <p v-if="subscription" class="expiry">服务期至 {{ formattedExpiry }}</p>
      </div>
      <van-form
        v-if="subscription?.can_redeem"
        class="renewal-form"
        @submit="redeem"
      >
        <van-field
          v-model="redemptionCode"
          name="redemptionCode"
          label="续期兑换码"
          maxlength="64"
          autocomplete="off"
          placeholder="输入平台提供的兑换码"
        />
        <div class="renewal-submit">
          <van-button
            block
            type="primary"
            native-type="submit"
            :loading="renewing"
            :disabled="!redemptionCode.trim()"
          >确认续期</van-button>
        </div>
      </van-form>
      <div class="actions">
        <van-button
          v-if="canOpenSecurity"
          block
          plain
          @click="router.push({ name: 'account-security' })"
        >账号安全</van-button>
        <van-button block type="danger" plain :loading="loggingOut" @click="logout">
          退出登录
        </van-button>
      </div>
    </template>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { showFailToast } from 'vant'
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
  : '当前只能查看到期状态并退出。Admin 续期入口将在订阅 API 完成后开放。')
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
    showFailToast((error as Error).message)
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
    showFailToast((error as Error).message)
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
    showFailToast((error as Error).message)
  } finally {
    loggingOut.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.status-view { min-height: 100%; overflow-y: auto; background: #f7f8fa; }
.loading { padding-top: 30vh; }
.status-card { margin: 40px 16px 20px; padding: 32px 20px; text-align: center; background: #fff; border-radius: 12px; }
.status-card h1 { margin: 16px 0 10px; font-size: 22px; }
.status-card p { margin: 0; color: #646566; line-height: 1.7; }
.status-card .expiry { margin-top: 10px; color: #ed6a0c; }
.renewal-form { margin: 0 16px 12px; overflow: hidden; border-radius: 12px; background: #fff; }
.renewal-submit { padding: 16px; }
.actions { display: grid; gap: 12px; padding: 12px 16px calc(24px + env(safe-area-inset-bottom)); }
</style>
