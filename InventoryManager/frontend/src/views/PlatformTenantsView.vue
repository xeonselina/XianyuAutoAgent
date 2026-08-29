<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'

import {
  apiErrorMessage,
  createTenant,
  listTenants,
  patchTenant,
  retryTenant,
  type PlatformTenant,
  type TenantPatch,
} from '@/api/auth'
import { useAuthStore } from '@/stores/auth'


const auth = useAuthStore()
const router = useRouter()
const tenants = ref<PlatformTenant[]>([])
const loading = ref(false)
const mutationBusy = ref(false)
const showCreate = ref(false)
const operationErrorMessage = ref('')
const listErrorMessage = ref('')
const errorMessage = computed(() => (
  [operationErrorMessage.value, listErrorMessage.value].filter(Boolean).join('；')
))
const form = reactive({
  name: '',
  adminPhone: '',
  initialPassword: '',
  confirmPassword: '',
  expiresAt: '',
})
const expiryDrafts = reactive<Record<number, string>>({})

const csrf = () => {
  if (!auth.platformCsrfToken) throw new Error('平台会话已失效')
  return auth.platformCsrfToken
}

const replaceTenant = (tenant: PlatformTenant) => {
  const index = tenants.value.findIndex((item) => item.id === tenant.id)
  if (index >= 0) tenants.value[index] = tenant
  else tenants.value.push(tenant)
}

const load = async (refreshAfterOperationFailure = false) => {
  loading.value = true
  listErrorMessage.value = ''
  try {
    tenants.value = await listTenants()
  } catch (error) {
    const detail = apiErrorMessage(error)
    listErrorMessage.value = refreshAfterOperationFailure
      ? `列表刷新失败，数据可能已过期：${detail}`
      : `列表加载失败：${detail}`
  } finally {
    loading.value = false
  }
}

const submitCreate = async () => {
  if (mutationBusy.value) return
  if (form.initialPassword.length < 12 || form.initialPassword.length > 128) {
    operationErrorMessage.value = '初始密码必须为 12 至 128 个字符'
    return
  }
  if (form.initialPassword !== form.confirmPassword) {
    operationErrorMessage.value = '两次输入的初始密码不一致'
    return
  }
  mutationBusy.value = true
  operationErrorMessage.value = ''
  try {
    const created = await createTenant(
      {
        name: form.name,
        admin_phone: form.adminPhone,
        initial_password: form.initialPassword,
        expires_at: new Date(form.expiresAt).toISOString(),
      },
      csrf(),
    )
    replaceTenant(created)
    Object.assign(form, {
      name: '',
      adminPhone: '',
      initialPassword: '',
      confirmPassword: '',
      expiresAt: '',
    })
    showCreate.value = false
  } catch (error) {
    operationErrorMessage.value = apiErrorMessage(error)
    await load(true)
  } finally {
    mutationBusy.value = false
  }
}

const update = async (tenant: PlatformTenant, patch: TenantPatch) => {
  if (mutationBusy.value) return
  mutationBusy.value = true
  operationErrorMessage.value = ''
  try {
    replaceTenant(await patchTenant(tenant.id, patch, csrf()))
  } catch (error) {
    operationErrorMessage.value = apiErrorMessage(error)
  } finally {
    mutationBusy.value = false
  }
}

const saveExpiry = async (tenant: PlatformTenant) => {
  const value = expiryDrafts[tenant.id]
  if (!value) return
  await update(tenant, { expires_at: new Date(value).toISOString() })
}

const retry = async (tenant: PlatformTenant) => {
  if (mutationBusy.value) return
  mutationBusy.value = true
  operationErrorMessage.value = ''
  try {
    replaceTenant(await retryTenant(tenant.id, csrf()))
  } catch (error) {
    operationErrorMessage.value = apiErrorMessage(error)
    await load(true)
  } finally {
    mutationBusy.value = false
  }
}

const logout = async () => {
  await auth.logoutPlatform()
  await router.replace('/platform/login')
}

onMounted(load)
</script>

<template>
  <main class="platform-page">
    <header>
      <div>
        <p>超级管理员</p>
        <h1>客户店铺</h1>
      </div>
      <div class="header-actions">
        <span>{{ auth.platformAdmin?.username }}</span>
        <button
          data-testid="new-tenant"
          type="button"
          :disabled="loading || mutationBusy"
          @click="showCreate = !showCreate"
        >
          创建店铺
        </button>
        <button type="button" class="secondary" @click="logout">退出</button>
      </div>
    </header>

    <form v-if="showCreate" class="create-form" @submit.prevent="submitCreate">
      <label>店铺名称<input v-model.trim="form.name" data-testid="tenant-name" :disabled="mutationBusy" required></label>
      <label>初始管理员手机号<input v-model.trim="form.adminPhone" data-testid="admin-phone" inputmode="numeric" :disabled="mutationBusy" required></label>
      <label>初始登录密码<input v-model="form.initialPassword" data-testid="initial-password" type="password" autocomplete="new-password" minlength="12" maxlength="128" :disabled="mutationBusy" required><small>12 至 128 个字符，由店铺管理员首次登录后自行修改</small></label>
      <label>确认初始密码<input v-model="form.confirmPassword" data-testid="confirm-password" type="password" autocomplete="new-password" minlength="12" maxlength="128" :disabled="mutationBusy" required></label>
      <label>服务到期时间<input v-model="form.expiresAt" data-testid="tenant-expiry" type="datetime-local" :disabled="mutationBusy" required></label>
      <button data-testid="create-tenant" type="submit" :disabled="mutationBusy">确认创建店铺</button>
    </form>

    <p v-if="errorMessage" class="error" role="alert">{{ errorMessage }}</p>
    <p v-if="loading">加载中…</p>
    <div v-else class="tenant-list">
      <article v-for="tenant in tenants" :key="tenant.id">
        <div class="tenant-title">
          <div>
            <h2>{{ tenant.name }}</h2>
            <p>{{ tenant.db_name }} · 初始管理员 {{ tenant.admin_phone }}</p>
          </div>
          <span :class="['badge', tenant.status]">{{ tenant.status }}</span>
          <span :class="['badge', tenant.provisioning_status]">
            {{ tenant.provisioning_status }}
          </span>
        </div>
        <p>当前到期时间：{{ new Date(tenant.expires_at).toLocaleString() }}</p>
        <div class="actions">
          <input
            v-model="expiryDrafts[tenant.id]"
            :data-testid="`expiry-${tenant.id}`"
            type="datetime-local"
            aria-label="新的到期时间"
            :disabled="mutationBusy"
          >
          <button
            :data-testid="`save-expiry-${tenant.id}`"
            type="button"
            :disabled="mutationBusy"
            @click="saveExpiry(tenant)"
          >
            保存到期时间
          </button>
          <button :data-testid="`extend-${tenant.id}`" type="button" :disabled="mutationBusy" @click="update(tenant, { extend_days: 30 })">
            增加 30 天
          </button>
          <button :data-testid="`status-${tenant.id}`" type="button" :disabled="mutationBusy" @click="update(tenant, { status: tenant.status === 'active' ? 'suspended' : 'active' })">
            {{ tenant.status === 'active' ? '暂停' : '恢复' }}
          </button>
          <button
            v-if="['provisioning', 'failed'].includes(tenant.provisioning_status)"
            :data-testid="`retry-${tenant.id}`"
            type="button"
            :disabled="mutationBusy"
            @click="retry(tenant)"
          >
            {{ tenant.provisioning_status === 'provisioning' ? '继续建库' : '重试建库' }}
          </button>
        </div>
        <p v-if="tenant.provisioning_error" class="error">
          {{ tenant.provisioning_error }}
        </p>
      </article>
    </div>
  </main>
</template>

<style scoped>
.platform-page { min-height: 100vh; padding: 28px; background: #f3f5f9; color: #101828; }
header, .tenant-title, .header-actions, .actions { display: flex; align-items: center; gap: 12px; }
header { justify-content: space-between; max-width: 1180px; margin: 0 auto 22px; }
header p, header h1, article h2, article p { margin: 0; }
.header-actions { flex-wrap: wrap; justify-content: flex-end; }
button { padding: 9px 13px; border: 0; border-radius: 7px; color: white; background: #175cd3; cursor: pointer; }
button.secondary { color: #344054; background: #e4e7ec; }
.create-form, article { max-width: 1180px; margin: 0 auto 16px; padding: 20px; border: 1px solid #e4e7ec; border-radius: 12px; background: white; }
.create-form { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; align-items: end; }
label { display: grid; gap: 6px; font-weight: 600; }
input { min-width: 150px; padding: 8px 10px; border: 1px solid #cbd5e1; border-radius: 7px; font: inherit; }
small { color: #667085; font-size: 12px; font-weight: 400; }
.create-form > button { justify-self: start; }
.tenant-title { flex-wrap: wrap; }
.tenant-title > div { flex: 1; }
.badge { padding: 4px 8px; border-radius: 999px; background: #eaecf0; font-size: 13px; }
.badge.active { color: #067647; background: #dcfae6; }
.badge.suspended, .badge.failed { color: #b42318; background: #fee4e2; }
.actions { margin-top: 15px; flex-wrap: wrap; }
.error { max-width: 1180px; margin: 12px auto; color: #b42318; }
@media (max-width: 760px) { .create-form { grid-template-columns: 1fr; } header { align-items: flex-start; } }
</style>
