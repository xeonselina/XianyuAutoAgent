<template>
  <main class="tenant-page">
    <el-card shadow="never">
      <template #header>
        <div class="page-header">
          <div>
            <p class="eyebrow">Control-plane directory</p>
            <h1>租户目录</h1>
            <p>这里只读取控制库最小投影，不打开租户业务库。</p>
          </div>
          <div class="header-actions">
            <el-button @click="router.push({ name: 'platform-redemption-codes' })">
              兑换码
            </el-button>
            <el-button @click="router.push({ name: 'platform-security' })">账号安全</el-button>
          </div>
        </div>
      </template>

      <div class="filters">
        <el-select v-model="status" placeholder="全部状态" clearable @change="resetAndLoad">
          <el-option
            v-for="option in statusOptions"
            :key="option"
            :label="option"
            :value="option"
          />
        </el-select>
        <el-button :loading="loading" @click="load">刷新</el-button>
      </div>

      <el-table v-loading="loading" :data="items" empty-text="暂无租户">
        <el-table-column label="租户" min-width="240">
          <template #default="scope">
            <strong>{{ scope.row.name || '未发布名称' }}</strong>
            <div class="secondary">{{ scope.row.tenant_id }}</div>
          </template>
        </el-table-column>
        <el-table-column prop="status" label="租户状态" min-width="150" />
        <el-table-column prop="subscription_status" label="订阅" min-width="110" />
        <el-table-column label="服务到期" min-width="180">
          <template #default="scope">{{ formatTime(scope.row.subscription_expires_at) }}</template>
        </el-table-column>
        <el-table-column prop="database_status" label="数据库路由" min-width="130" />
        <el-table-column label="操作" width="100" align="right">
          <template #default="scope">
            <el-button link type="primary" @click="openDetail(scope.row.tenant_id)">
              查看
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="pager">
        <el-button :disabled="page <= 1 || loading" @click="movePage(-1)">上一页</el-button>
        <span>第 {{ page }} 页</span>
        <el-button :disabled="!hasMore || loading" @click="movePage(1)">下一页</el-button>
      </div>
    </el-card>

    <el-drawer v-model="drawerOpen" title="租户控制面详情" size="min(560px, 92vw)">
      <div v-loading="detailLoading">
        <template v-if="detail">
          <el-descriptions :column="1" border>
            <el-descriptions-item label="租户 UUID">{{ detail.tenant_id }}</el-descriptions-item>
            <el-descriptions-item label="名称">{{ detail.name || '未发布' }}</el-descriptions-item>
            <el-descriptions-item label="状态">{{ detail.status }}</el-descriptions-item>
            <el-descriptions-item label="Access version">{{ detail.access_version }}</el-descriptions-item>
            <el-descriptions-item label="时区">{{ detail.timezone }}</el-descriptions-item>
            <el-descriptions-item label="订阅">
              {{ detail.subscription ? `${detail.subscription.status} / ${formatTime(detail.subscription.expires_at)}` : '未建立' }}
            </el-descriptions-item>
            <el-descriptions-item label="数据库路由">
              {{ detail.database_route ? `${detail.database_route.status} / route v${detail.database_route.route_version}` : '未建立' }}
            </el-descriptions-item>
            <el-descriptions-item label="DML login state">
              {{ detail.database_route ? `${detail.database_route.dml_desired_login_state || '-'} / ${detail.database_route.dml_observed_login_state || '-'}` : '-' }}
            </el-descriptions-item>
          </el-descriptions>
          <el-alert
            class="detail-note"
            title="该页面没有 tenant DML 身份，也不包含 settings、数据库名、账号、手机号或业务行。"
            type="info"
            :closable="false"
          />
          <div class="detail-actions">
            <el-button
              type="primary"
              @click="router.push({
                name: 'platform-subscription-adjustment',
                params: { tenantId: detail.tenant_id },
              })"
            >调整服务期</el-button>
          </div>

          <section class="inventory-read-section">
            <div class="section-heading">
              <div>
                <h2>仓库与设备只读排障</h2>
                <p>复用同一 SELECT-only 租户边界；不返回仓库联系人、地址、设备序列号或生命周期备注。</p>
              </div>
            </div>
            <el-alert
              v-if="!tenantBusinessReadable"
              title="该租户当前状态不允许读取业务库。"
              type="warning"
              :closable="false"
            />
            <div v-else v-loading="inventoryReadLoading" class="inventory-grid">
              <div>
                <h3>仓库</h3>
                <el-table :data="warehouses" empty-text="暂无仓库">
                  <el-table-column prop="name" label="名称" min-width="140" />
                  <el-table-column prop="status" label="状态" width="90" />
                  <el-table-column prop="setup_state" label="设置" width="90" />
                  <el-table-column label="默认仓" width="80">
                    <template #default="scope">{{ scope.row.is_default ? '是' : '否' }}</template>
                  </el-table-column>
                </el-table>
              </div>
              <div>
                <h3>设备</h3>
                <el-table :data="devices" empty-text="暂无设备">
                  <el-table-column prop="name" label="名称" min-width="140" />
                  <el-table-column prop="model" label="型号" min-width="100" />
                  <el-table-column prop="lifecycle_status" label="生命周期" min-width="110" />
                  <el-table-column prop="warehouse_id" label="仓库 ID" width="90" />
                </el-table>
              </div>
              <el-alert
                v-if="inventoryReadTruncated"
                class="inventory-limit-note"
                title="当前仅展示每类前 100 条，请使用后续分页视图继续查看。"
                type="info"
                :closable="false"
              />
            </div>
          </section>

          <section class="rental-read-section">
            <div class="section-heading">
              <div>
                <h2>租赁只读排障</h2>
                <p>单租户 SELECT-only 查询；客户信息默认脱敏，不返回地址、备注、买家或运单号。</p>
              </div>
              <el-select
                v-model="rentalStatus"
                class="rental-status"
                placeholder="全部租赁状态"
                clearable
                :disabled="!tenantBusinessReadable"
                @change="resetRentalsAndLoad"
              >
                <el-option
                  v-for="option in rentalStatusOptions"
                  :key="option"
                  :label="option"
                  :value="option"
                />
              </el-select>
            </div>

            <el-alert
              v-if="!tenantBusinessReadable"
              title="该租户当前状态不允许读取业务库。"
              type="warning"
              :closable="false"
            />
            <template v-else>
              <el-table
                v-loading="rentalLoading"
                :data="rentals"
                empty-text="暂无可显示的主租赁"
              >
                <el-table-column prop="rental_id" label="租赁" width="80" />
                <el-table-column label="设备" min-width="150">
                  <template #default="scope">
                    <strong>{{ scope.row.device.name }}</strong>
                    <div class="secondary">{{ scope.row.device.model }}</div>
                  </template>
                </el-table-column>
                <el-table-column prop="status" label="状态" min-width="130" />
                <el-table-column label="租期" min-width="180">
                  <template #default="scope">
                    {{ scope.row.start_date || '-' }} — {{ scope.row.end_date || '-' }}
                  </template>
                </el-table-column>
                <el-table-column label="客户（脱敏）" min-width="180">
                  <template #default="scope">
                    <span>{{ scope.row.customer.name_masked || '-' }}</span>
                    <div class="secondary">
                      {{ scope.row.customer.phone_masked || '-' }} ·
                      {{ scope.row.customer.region_masked || '未设置地区' }}
                    </div>
                  </template>
                </el-table-column>
                <el-table-column label="完整客户信息" width="112" align="right">
                  <template #default="scope">
                    <el-button
                      link
                      type="primary"
                      @click="openPiiDialog(scope.row.rental_id)"
                    >按需查看</el-button>
                  </template>
                </el-table-column>
              </el-table>

              <div class="pager compact-pager">
                <el-button
                  :disabled="rentalPage <= 1 || rentalLoading"
                  @click="moveRentalPage(-1)"
                >上一页</el-button>
                <span>第 {{ rentalPage }} 页</span>
                <el-button
                  :disabled="!rentalsHaveMore || rentalLoading"
                  @click="moveRentalPage(1)"
                >下一页</el-button>
              </div>
            </template>
          </section>
        </template>
      </div>
    </el-drawer>

    <el-dialog
      v-model="piiDialogOpen"
      title="按需读取完整客户信息"
      width="min(520px, 92vw)"
      :close-on-click-modal="false"
    >
      <el-alert
        title="只读取当前租赁；理由和读取结果会被审计，关闭后页面立即清空完整信息。"
        type="warning"
        :closable="false"
      />
      <el-form class="pii-form" label-position="top">
        <el-form-item label="审计理由代码">
          <el-input
            v-model="piiReason"
            maxlength="40"
            placeholder="例如 support_case"
            autocomplete="off"
          />
        </el-form-item>
        <el-button
          type="primary"
          :loading="piiLoading"
          @click="loadCustomerPii"
        >读取一次</el-button>
      </el-form>
      <el-descriptions v-if="piiDetail" class="pii-result" :column="1" border>
        <el-descriptions-item label="租赁">{{ piiDetail.rental_id }}</el-descriptions-item>
        <el-descriptions-item label="姓名">{{ piiDetail.customer.name || '-' }}</el-descriptions-item>
        <el-descriptions-item label="电话">{{ piiDetail.customer.phone || '-' }}</el-descriptions-item>
        <el-descriptions-item label="地址">{{ customerAddress }}</el-descriptions-item>
      </el-descriptions>
    </el-dialog>
  </main>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useRouter } from 'vue-router'

import {
  getPlatformTenant,
  getPlatformTenantRentalCustomerPii,
  listPlatformTenantDevices,
  listPlatformTenantRentals,
  listPlatformTenantWarehouses,
  listPlatformTenants,
  type PlatformTenantDetail,
  type PlatformTenantCustomerPii,
  type PlatformTenantDeviceItem,
  type PlatformTenantDirectoryItem,
  type PlatformTenantRentalItem,
  type PlatformTenantWarehouseItem,
} from '@/api/platformIdentity'

const statusOptions = [
  'provisioning', 'active', 'expired', 'suspending', 'suspended',
  'resuming', 'deletion_cooling_off', 'deletion_committing', 'deleted',
]
const router = useRouter()
const readableTenantStatuses = new Set([
  'active', 'expired', 'suspending', 'suspended', 'resuming',
  'deletion_cooling_off',
])
const rentalStatusOptions = [
  'not_shipped', 'scheduled_for_shipping', 'shipped',
  'returned', 'completed', 'cancelled',
]
const loading = ref(false)
const detailLoading = ref(false)
const rentalLoading = ref(false)
const inventoryReadLoading = ref(false)
const piiLoading = ref(false)
const drawerOpen = ref(false)
const piiDialogOpen = ref(false)
const status = ref('')
const page = ref(1)
const pageSize = 25
const hasMore = ref(false)
const items = ref<PlatformTenantDirectoryItem[]>([])
const detail = ref<PlatformTenantDetail | null>(null)
const selectedTenantId = ref<string | null>(null)
const rentals = ref<PlatformTenantRentalItem[]>([])
const devices = ref<PlatformTenantDeviceItem[]>([])
const warehouses = ref<PlatformTenantWarehouseItem[]>([])
const devicesHaveMore = ref(false)
const warehousesHaveMore = ref(false)
const rentalPage = ref(1)
const rentalPageSize = 25
const rentalsHaveMore = ref(false)
const rentalStatus = ref('')
const piiReason = ref('')
const selectedPiiRentalId = ref<number | null>(null)
const piiDetail = ref<PlatformTenantCustomerPii | null>(null)
const tenantBusinessReadable = computed(() => (
  detail.value !== null && readableTenantStatuses.has(detail.value.status)
))
const inventoryReadTruncated = computed(() => (
  devicesHaveMore.value || warehousesHaveMore.value
))
const customerAddress = computed(() => {
  const address = piiDetail.value?.customer.address
  if (!address) return '-'
  return [address.province, address.city, address.district, address.detail]
    .filter((value): value is string => Boolean(value))
    .join('') || '-'
})
let detailController: AbortController | null = null
let rentalController: AbortController | null = null
let inventoryController: AbortController | null = null
let piiController: AbortController | null = null
let detailGeneration = 0
let rentalGeneration = 0
let inventoryGeneration = 0
let piiGeneration = 0

const formatTime = (value: string | null) => value
  ? new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value))
  : '-'

const load = async () => {
  loading.value = true
  try {
    const result = await listPlatformTenants({
      page: page.value,
      page_size: pageSize,
      status: status.value || undefined,
    })
    items.value = result.items
    hasMore.value = result.has_more
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    loading.value = false
  }
}

const resetAndLoad = async () => {
  page.value = 1
  await load()
}

const movePage = async (delta: number) => {
  const target = page.value + delta
  if (target < 1 || (delta > 0 && !hasMore.value)) return
  page.value = target
  await load()
}

const clearRentalState = () => {
  rentalController?.abort()
  rentalController = null
  rentalGeneration += 1
  rentalLoading.value = false
  rentals.value = []
  rentalPage.value = 1
  rentalsHaveMore.value = false
  rentalStatus.value = ''
  inventoryController?.abort()
  inventoryController = null
  inventoryGeneration += 1
  inventoryReadLoading.value = false
  devices.value = []
  warehouses.value = []
  devicesHaveMore.value = false
  warehousesHaveMore.value = false
  piiDialogOpen.value = false
  clearPiiState()
}

const loadInventoryOverview = async () => {
  const tenantId = selectedTenantId.value
  if (!tenantId || !tenantBusinessReadable.value) return
  inventoryController?.abort()
  const controller = new AbortController()
  inventoryController = controller
  const generation = ++inventoryGeneration
  inventoryReadLoading.value = true
  devices.value = []
  warehouses.value = []
  try {
    const [devicePage, warehousePage] = await Promise.all([
      listPlatformTenantDevices(
        tenantId,
        { page: 1, page_size: 100 },
        controller.signal,
      ),
      listPlatformTenantWarehouses(
        tenantId,
        { page: 1, page_size: 100 },
        controller.signal,
      ),
    ])
    if (
      generation !== inventoryGeneration
      || selectedTenantId.value !== tenantId
    ) return
    devices.value = devicePage.items
    warehouses.value = warehousePage.items
    devicesHaveMore.value = devicePage.has_more
    warehousesHaveMore.value = warehousePage.has_more
  } catch (error) {
    if (generation !== inventoryGeneration || controller.signal.aborted) return
    ElMessage.error((error as Error).message)
  } finally {
    if (generation === inventoryGeneration) {
      inventoryReadLoading.value = false
      if (inventoryController === controller) inventoryController = null
    }
  }
}

function clearPiiState() {
  piiController?.abort()
  piiController = null
  piiGeneration += 1
  piiLoading.value = false
  selectedPiiRentalId.value = null
  piiReason.value = ''
  piiDetail.value = null
}

const openPiiDialog = (rentalId: number) => {
  clearPiiState()
  selectedPiiRentalId.value = rentalId
  piiDialogOpen.value = true
}

const loadCustomerPii = async () => {
  const tenantId = selectedTenantId.value
  const rentalId = selectedPiiRentalId.value
  const reason = piiReason.value.trim()
  if (!tenantId || rentalId === null || !tenantBusinessReadable.value) return
  if (!/^[a-z][a-z0-9_.:-]{0,39}$/.test(reason)) {
    ElMessage.error('审计理由须为 1–40 位小写代码')
    return
  }
  piiController?.abort()
  const controller = new AbortController()
  piiController = controller
  const generation = ++piiGeneration
  piiLoading.value = true
  piiDetail.value = null
  try {
    const result = await getPlatformTenantRentalCustomerPii(
      tenantId,
      rentalId,
      reason,
      controller.signal,
    )
    if (
      generation !== piiGeneration
      || selectedTenantId.value !== tenantId
      || selectedPiiRentalId.value !== rentalId
    ) return
    piiDetail.value = result
  } catch (error) {
    if (generation !== piiGeneration || controller.signal.aborted) return
    ElMessage.error((error as Error).message)
  } finally {
    if (generation === piiGeneration) {
      piiLoading.value = false
      if (piiController === controller) piiController = null
    }
  }
}

const loadRentals = async () => {
  const tenantId = selectedTenantId.value
  if (!tenantId || !tenantBusinessReadable.value) return
  rentalController?.abort()
  const controller = new AbortController()
  rentalController = controller
  const generation = ++rentalGeneration
  rentalLoading.value = true
  rentals.value = []
  rentalsHaveMore.value = false
  try {
    const result = await listPlatformTenantRentals(
      tenantId,
      {
        page: rentalPage.value,
        page_size: rentalPageSize,
        status: rentalStatus.value || undefined,
      },
      controller.signal,
    )
    if (
      generation !== rentalGeneration
      || selectedTenantId.value !== tenantId
    ) return
    rentals.value = result.items
    rentalsHaveMore.value = result.has_more
  } catch (error) {
    if (generation !== rentalGeneration || controller.signal.aborted) return
    ElMessage.error((error as Error).message)
  } finally {
    if (generation === rentalGeneration) {
      rentalLoading.value = false
      if (rentalController === controller) rentalController = null
    }
  }
}

const resetRentalsAndLoad = async () => {
  rentalPage.value = 1
  await loadRentals()
}

const moveRentalPage = async (delta: number) => {
  const target = rentalPage.value + delta
  if (target < 1 || (delta > 0 && !rentalsHaveMore.value)) return
  rentalPage.value = target
  await loadRentals()
}

const openDetail = async (tenantId: string) => {
  detailController?.abort()
  clearRentalState()
  selectedTenantId.value = tenantId
  const controller = new AbortController()
  detailController = controller
  const generation = ++detailGeneration
  drawerOpen.value = true
  detail.value = null
  detailLoading.value = true
  try {
    const result = await getPlatformTenant(tenantId, controller.signal)
    if (
      generation !== detailGeneration
      || selectedTenantId.value !== tenantId
    ) return
    detail.value = result
    detailLoading.value = false
    await Promise.all([loadRentals(), loadInventoryOverview()])
  } catch (error) {
    if (generation !== detailGeneration || controller.signal.aborted) return
    drawerOpen.value = false
    ElMessage.error((error as Error).message)
  } finally {
    if (generation === detailGeneration) {
      detailLoading.value = false
      if (detailController === controller) detailController = null
    }
  }
}

watch(drawerOpen, (open) => {
  if (open) return
  detailController?.abort()
  detailController = null
  detailGeneration += 1
  detailLoading.value = false
  detail.value = null
  selectedTenantId.value = null
  clearRentalState()
})

watch(piiDialogOpen, (open) => {
  if (!open) clearPiiState()
})

onMounted(load)
onBeforeUnmount(() => {
  detailController?.abort()
  rentalController?.abort()
  inventoryController?.abort()
  piiController?.abort()
})
</script>

<style scoped>
.tenant-page { min-height: 100vh; padding: 32px; background: #111827; }
.tenant-page > .el-card { max-width: 1180px; margin: 0 auto; }
.page-header { display: flex; justify-content: space-between; align-items: flex-start; gap: 24px; }
.eyebrow { margin: 0 0 6px; color: #409eff; font-size: 12px; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; }
h1 { margin: 0 0 8px; }
.page-header p:not(.eyebrow) { margin: 0; color: #606266; }
.filters { display: flex; justify-content: flex-end; gap: 12px; margin-bottom: 18px; }
.filters .el-select { width: 220px; }
.secondary { margin-top: 4px; color: #909399; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; }
.pager { display: flex; justify-content: center; align-items: center; gap: 16px; margin-top: 22px; }
.detail-note { margin-top: 20px; }
.inventory-read-section { margin-top: 28px; }
.inventory-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px; }
.inventory-grid h3 { margin: 0 0 10px; font-size: 15px; }
.inventory-limit-note { grid-column: 1 / -1; }
.rental-read-section { margin-top: 28px; }
.section-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; margin-bottom: 16px; }
.section-heading h2 { margin: 0 0 6px; font-size: 18px; }
.section-heading p { margin: 0; color: #606266; font-size: 13px; line-height: 1.5; }
.rental-status { width: 210px; flex: 0 0 auto; }
.compact-pager { margin-top: 14px; }
.pii-form { margin-top: 18px; }
.pii-result { margin-top: 20px; }
@media (max-width: 840px) { .inventory-grid { grid-template-columns: 1fr; } }
</style>
