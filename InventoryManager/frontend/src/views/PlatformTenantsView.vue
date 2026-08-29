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
const activeTenantCount = computed(() => (
  tenants.value.filter((tenant) => tenant.status === 'active').length
))
const suspendedTenantCount = computed(() => (
  tenants.value.filter((tenant) => tenant.status === 'suspended').length
))
const provisioningIssueCount = computed(() => (
  tenants.value.filter((tenant) => tenant.provisioning_status !== 'active').length
))
const form = reactive({
  name: '',
  adminPhone: '',
  initialPassword: '',
  confirmPassword: '',
  expiresAt: '',
})
const expiryDrafts = reactive<Record<number, string>>({})

const tenantStatusLabel = (status: PlatformTenant['status']) => (
  status === 'active' ? '服务中' : '已暂停'
)

const provisioningStatusLabel = (status: PlatformTenant['provisioning_status']) => ({
  active: '数据库就绪',
  provisioning: '建库中',
  failed: '建库失败',
}[status])

const formatExpiry = (value: string) => new Date(value).toLocaleString('zh-CN', {
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
})

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
  <main class="platform-page" data-testid="platform-store-page">
    <header class="platform-header">
      <div class="platform-heading">
        <p class="eyebrow">Rental Manager · 平台控制台</p>
        <h1>客户店铺管理</h1>
        <p class="subtitle">创建客户店铺、设置首位店铺管理员，并管理服务状态与到期时间。</p>
      </div>
      <div class="header-actions">
        <div class="platform-user">
          <small>当前超级管理员</small>
          <strong>{{ auth.platformAdmin?.username }}</strong>
        </div>
        <button
          data-testid="new-tenant"
          type="button"
          class="primary"
          :disabled="loading || mutationBusy"
          :aria-expanded="showCreate"
          @click="showCreate = !showCreate"
        >
          {{ showCreate ? '收起创建表单' : '创建客户店铺' }}
        </button>
        <button type="button" class="secondary" @click="logout">退出</button>
      </div>
    </header>

    <section class="summary-grid" aria-label="客户店铺概览">
      <div class="summary-card">
        <span>客户店铺</span>
        <strong>{{ tenants.length }}</strong>
        <small>平台当前全部店铺</small>
      </div>
      <div class="summary-card active-summary">
        <span>服务中</span>
        <strong>{{ activeTenantCount }}</strong>
        <small>可以正常登录使用</small>
      </div>
      <div class="summary-card">
        <span>已暂停</span>
        <strong>{{ suspendedTenantCount }}</strong>
        <small>业务数据仍然保留</small>
      </div>
      <div class="summary-card" :class="{ 'warning-summary': provisioningIssueCount > 0 }">
        <span>需要处理</span>
        <strong>{{ provisioningIssueCount }}</strong>
        <small>建库中或建库失败</small>
      </div>
    </section>

    <section v-if="showCreate" class="create-panel">
      <div class="section-heading">
        <div>
          <p class="eyebrow">新客户入驻</p>
          <h2>创建客户店铺</h2>
        </div>
        <p>创建完成后，初始管理员即可使用手机号和初始密码从店铺登录页进入。</p>
      </div>
      <form class="create-form" @submit.prevent="submitCreate">
        <label>店铺名称<input v-model.trim="form.name" data-testid="tenant-name" :disabled="mutationBusy" placeholder="例如：深圳光影租界" required></label>
        <label>初始管理员手机号<input v-model.trim="form.adminPhone" data-testid="admin-phone" inputmode="numeric" maxlength="11" :disabled="mutationBusy" placeholder="大陆手机号" required></label>
        <label>初始登录密码<input v-model="form.initialPassword" data-testid="initial-password" type="password" autocomplete="new-password" minlength="12" maxlength="128" :disabled="mutationBusy" placeholder="12 至 128 个字符" required><small>只用于首位店铺管理员登录，不是 App Key 或 App Secret。</small></label>
        <label>确认初始密码<input v-model="form.confirmPassword" data-testid="confirm-password" type="password" autocomplete="new-password" minlength="12" maxlength="128" :disabled="mutationBusy" placeholder="再次输入初始密码" required></label>
        <label>服务到期时间<input v-model="form.expiresAt" data-testid="tenant-expiry" type="datetime-local" :disabled="mutationBusy" required><small>到期后停止业务访问，但保留店铺数据。</small></label>
        <div class="form-footer">
          <p>密码仅在本次创建时使用，服务端只保存密码哈希且不会回显。</p>
          <div>
            <button type="button" class="secondary" :disabled="mutationBusy" @click="showCreate = false">取消</button>
            <button data-testid="create-tenant" type="submit" class="primary" :disabled="mutationBusy">确认创建店铺</button>
          </div>
        </div>
      </form>
    </section>

    <p v-if="errorMessage" class="error" role="alert">{{ errorMessage }}</p>
    <section class="tenant-section">
      <div class="section-heading list-heading">
        <div>
          <p class="eyebrow">店铺生命周期</p>
          <h2>客户店铺列表</h2>
        </div>
        <span>{{ tenants.length }} 家店铺</span>
      </div>
      <p v-if="loading" class="loading-state">正在加载客户店铺…</p>
      <div v-else class="tenant-list">
      <article v-for="tenant in tenants" :key="tenant.id">
        <div class="tenant-title">
          <div>
            <h2>{{ tenant.name }}</h2>
            <p>初始管理员 {{ tenant.admin_phone }} · 店铺编号 #{{ tenant.id }}</p>
          </div>
          <span :class="['badge', tenant.status]">{{ tenantStatusLabel(tenant.status) }}</span>
          <span :class="['badge', tenant.provisioning_status]">
            {{ provisioningStatusLabel(tenant.provisioning_status) }}
          </span>
        </div>
        <div class="tenant-meta">
          <div><small>服务状态</small><strong>{{ tenantStatusLabel(tenant.status) }}</strong></div>
          <div><small>服务到期</small><strong>{{ formatExpiry(tenant.expires_at) }}</strong></div>
          <div><small>业务数据库</small><strong>{{ tenant.db_name }}</strong></div>
        </div>
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
    </section>
  </main>
</template>

<style scoped>
.platform-page { min-height: 100vh; padding: 32px; background: #f4f6fa; color: #101828; }
.platform-header, .tenant-title, .header-actions, .actions, .section-heading, .form-footer { display: flex; align-items: center; gap: 12px; }
.platform-header, .summary-grid, .create-panel, .tenant-section { width: min(1180px, 100%); margin-inline: auto; }
.platform-header { justify-content: space-between; margin-bottom: 24px; }
.platform-heading { max-width: 650px; }
.platform-heading h1 { margin: 3px 0 7px; font-size: clamp(28px, 4vw, 38px); letter-spacing: -.03em; }
.eyebrow { margin: 0; color: #175cd3; font-size: 12px; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; }
.subtitle, .section-heading > p { margin: 0; color: #667085; line-height: 1.5; }
.header-actions { flex-wrap: wrap; justify-content: flex-end; }
.platform-user { display: grid; padding-right: 5px; text-align: right; }
.platform-user small { color: #98a2b3; }
.platform-user strong { font-size: 14px; }
button { padding: 10px 14px; border: 1px solid transparent; border-radius: 8px; font: inherit; font-weight: 650; cursor: pointer; }
button.primary { color: white; background: #175cd3; }
button.secondary { color: #344054; border-color: #d0d5dd; background: white; }
button:disabled { opacity: .55; cursor: default; }
.summary-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 14px; margin-bottom: 20px; }
.summary-card { display: grid; gap: 4px; padding: 18px 20px; border: 1px solid #e4e7ec; border-radius: 12px; background: white; }
.summary-card span, .summary-card small { color: #667085; }
.summary-card strong { font-size: 28px; }
.active-summary { border-color: #abefc6; background: #f6fef9; }
.warning-summary { border-color: #fedf89; background: #fffaeb; }
.create-panel, .tenant-section { margin-bottom: 20px; padding: 22px; border: 1px solid #e4e7ec; border-radius: 14px; background: white; box-shadow: 0 1px 3px rgb(16 24 40 / 4%); }
.section-heading { justify-content: space-between; margin-bottom: 20px; }
.section-heading h2 { margin: 3px 0 0; font-size: 20px; }
.section-heading > p { max-width: 560px; text-align: right; }
.list-heading { padding-bottom: 16px; border-bottom: 1px solid #eaecf0; }
.list-heading > span { color: #475467; font-size: 14px; }
.create-form { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px; align-items: start; }
label { display: grid; gap: 6px; font-weight: 600; }
input { min-width: 150px; padding: 10px 12px; border: 1px solid #cbd5e1; border-radius: 8px; font: inherit; }
input:focus { border-color: #84adff; outline: 3px solid #eff4ff; }
small { color: #667085; font-size: 12px; font-weight: 400; }
.form-footer { grid-column: 1 / -1; justify-content: space-between; padding-top: 4px; }
.form-footer p { margin: 0; color: #667085; font-size: 13px; }
.form-footer > div { display: flex; gap: 10px; }
.tenant-list { display: grid; gap: 14px; }
article { padding: 20px; border: 1px solid #e4e7ec; border-radius: 12px; background: #fcfcfd; }
article h2, article p { margin: 0; }
.tenant-title { flex-wrap: wrap; }
.tenant-title > div { flex: 1; }
.tenant-title p { margin-top: 4px; color: #667085; font-size: 13px; }
.badge { padding: 4px 8px; border-radius: 999px; background: #eaecf0; font-size: 13px; }
.badge.active { color: #067647; background: #dcfae6; }
.badge.suspended, .badge.failed { color: #b42318; background: #fee4e2; }
.badge.provisioning { color: #b54708; background: #fef0c7; }
.tenant-meta { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; margin-top: 16px; }
.tenant-meta > div { display: grid; gap: 4px; min-width: 0; padding: 12px; border-radius: 8px; background: white; }
.tenant-meta strong { overflow: hidden; font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }
.actions { margin-top: 15px; flex-wrap: wrap; }
.error { width: min(1180px, 100%); margin: 12px auto; color: #b42318; }
.loading-state { padding: 18px 0; color: #667085; }
@media (max-width: 900px) {
  .summary-grid { grid-template-columns: repeat(2, 1fr); }
  .platform-header, .section-heading, .form-footer { align-items: flex-start; flex-direction: column; }
  .header-actions { justify-content: flex-start; }
  .platform-user { text-align: left; }
  .section-heading > p { text-align: left; }
  .form-footer > div { width: 100%; justify-content: flex-end; }
}
@media (max-width: 640px) {
  .platform-page { padding: 20px 14px; }
  .summary-grid, .create-form, .tenant-meta { grid-template-columns: 1fr; }
  .create-panel, .tenant-section { padding: 17px; }
  .form-footer > div { justify-content: stretch; }
  .form-footer button { flex: 1; }
  .actions input { width: 100%; }
}
</style>
