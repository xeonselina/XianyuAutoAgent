<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import dayjs from 'dayjs'
import { ElMessage } from 'element-plus'
import { ArrowLeft, CopyDocument, EditPen, Refresh } from '@element-plus/icons-vue'

import {
  listRelayCases,
  refreshRelayTracking,
  refreshRelayTrackingBatch,
} from '@/api/relayCases'
import RelayStatusDialog from '@/components/relay/RelayStatusDialog.vue'
import { relayEquipmentWarningText } from '@/utils/relayEquipmentWarnings'
import type {
  RelayAccessory,
  RelayCase,
  RelayCaseListResponse,
  RelayCaseStatus,
  RelayCustomer,
} from '@/types/relayCase'

const OPEN_STATUSES: RelayCaseStatus[] = [
  'pending',
  'notified',
  'agreed',
  'shipped',
]

const statusOptions: Array<{ value: RelayCaseStatus; label: string }> = [
  { value: 'pending', label: '待处理' },
  { value: 'notified', label: '已通知' },
  { value: 'agreed', label: '已同意' },
  { value: 'shipped', label: '已寄出' },
  { value: 'completed', label: '已完成' },
]

const statusLabels: Record<RelayCaseStatus, string> = Object.fromEntries(
  statusOptions.map((option) => [option.value, option.label]),
) as Record<RelayCaseStatus, string>

const statusTypes: Record<RelayCaseStatus, 'info' | 'primary' | 'warning' | 'success'> = {
  pending: 'info',
  notified: 'primary',
  agreed: 'warning',
  shipped: 'primary',
  completed: 'success',
}

const lensLabels: Record<string, string> = {
  lens_400mm: '400MM 镜头',
  lens_200mm: '200MM 镜头',
  lens_dual: '双镜头',
  bare: '裸机',
}

const loading = ref(false)
const batchRefreshing = ref(false)
const items = ref<RelayCase[]>([])
const total = ref(0)
const page = ref(1)
const perPage = ref(50)
const selectedStatuses = ref<RelayCaseStatus[]>([...OPEN_STATUSES])
const shipDateRange = ref<[string, string]>([
  dayjs().subtract(3, 'day').format('YYYY-MM-DD'),
  dayjs().add(5, 'day').format('YYYY-MM-DD'),
])
const dialogVisible = ref(false)
const activeCase = ref<RelayCase | null>(null)

const refreshableCaseIds = computed(() => items.value
  .filter((item) => item.case_id !== null && ['shipped', 'completed'].includes(item.status))
  .map((item) => item.case_id as number))

function lensText(value: string | null) {
  if (!value) return '未填写镜头'
  return lensLabels[value] || value
}

function accessoryText(accessories: RelayAccessory[]) {
  if (!accessories.length) return '无附件'
  return accessories.map((accessory) => accessory.name).join('、')
}

function rentalPeriod(customer: RelayCustomer) {
  return `${customer.start_date} → ${customer.end_date}`
}

function relayNoticeText(relayCase: RelayCase) {
  const destination = relayCase.successor.destination?.trim() || '地址未填写'
  return `你好，因为档期紧张，请你帮忙在${relayCase.planned_ship_date}将设备用顺丰标快寄给下一个客户，地址如下： ${destination}。邮费由我们承担。为避免纠纷，寄出前可以拍个视频，拍下寄出的有什么东西。谢谢`
}

function fallbackCopy(text: string) {
  const textarea = document.createElement('textarea')
  textarea.value = text
  textarea.setAttribute('readonly', '')
  textarea.style.position = 'fixed'
  textarea.style.opacity = '0'
  document.body.appendChild(textarea)
  textarea.select()
  try {
    return document.execCommand('copy')
  } catch {
    return false
  } finally {
    textarea.remove()
  }
}

async function copyRelayNotice(relayCase: RelayCase) {
  const text = relayNoticeText(relayCase)
  let copied = false
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text)
      copied = true
    }
  } catch {
    copied = false
  }
  if (!copied) copied = fallbackCopy(text)
  if (copied) ElMessage.success('通知文案已复制')
  else ElMessage.error('复制失败，请手动选择文案复制')
}

function statusLabel(status: RelayCaseStatus) {
  return statusLabels[status]
}

function statusType(status: RelayCaseStatus) {
  return statusTypes[status]
}

async function loadCases() {
  if (!selectedStatuses.value.length) {
    items.value = []
    total.value = 0
    return
  }
  if (!shipDateRange.value?.[0] || !shipDateRange.value?.[1]) return

  loading.value = true
  try {
    const response: RelayCaseListResponse = await listRelayCases({
      statuses: selectedStatuses.value,
      shipDateFrom: shipDateRange.value[0],
      shipDateTo: shipDateRange.value[1],
      page: page.value,
      perPage: perPage.value,
    })
    items.value = response.items
    total.value = response.total
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '加载接力列表失败')
  } finally {
    loading.value = false
  }
}

function applyFilters() {
  page.value = 1
  void loadCases()
}

function resetFilters() {
  selectedStatuses.value = [...OPEN_STATUSES]
  shipDateRange.value = [
    dayjs().subtract(3, 'day').format('YYYY-MM-DD'),
    dayjs().add(5, 'day').format('YYYY-MM-DD'),
  ]
  applyFilters()
}

function editCase(relayCase: RelayCase) {
  activeCase.value = relayCase
  dialogVisible.value = true
}

async function refreshOne(relayCase: RelayCase) {
  if (relayCase.case_id === null) return
  try {
    await refreshRelayTracking(relayCase.case_id)
    ElMessage.success('物流状态已刷新')
    await loadCases()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '物流刷新失败')
  }
}

async function refreshBatch() {
  if (!refreshableCaseIds.value.length) {
    ElMessage.info('当前页没有可刷新的顺丰运单')
    return
  }
  batchRefreshing.value = true
  try {
    const result = await refreshRelayTrackingBatch(refreshableCaseIds.value)
    ElMessage.success(`已刷新 ${result.success_count}/${result.total} 条物流`)
    await loadCases()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '批量刷新失败')
  } finally {
    batchRefreshing.value = false
  }
}

function handleSaved() {
  void loadCases()
}

function goBack() {
  window.history.back()
}

onMounted(loadCases)
</script>

<template>
  <main class="relay-page">
    <header class="page-header">
      <div class="title-area">
        <el-button :icon="ArrowLeft" circle aria-label="返回" @click="goBack" />
        <div>
          <h1>接力管理</h1>
          <p>集中处理前一位客户直接转寄给后一位客户的潜在组合</p>
        </div>
      </div>
      <el-button
        :icon="Refresh"
        :loading="batchRefreshing"
        :disabled="!refreshableCaseIds.length"
        data-testid="batch-refresh"
        @click="refreshBatch"
      >
        批量刷新物流
      </el-button>
    </header>

    <section class="filter-bar">
      <div class="filter-item status-filter">
        <span class="filter-label">状态</span>
        <el-select
          v-model="selectedStatuses"
          multiple
          collapse-tags
          collapse-tags-tooltip
          placeholder="请选择状态"
        >
          <el-option
            v-for="option in statusOptions"
            :key="option.value"
            :label="option.label"
            :value="option.value"
          />
        </el-select>
      </div>
      <div class="filter-item date-filter">
        <span class="filter-label">寄出时间范围</span>
        <el-date-picker
          v-model="shipDateRange"
          type="daterange"
          value-format="YYYY-MM-DD"
          start-placeholder="开始日期"
          end-placeholder="结束日期"
          range-separator="至"
        />
      </div>
      <div class="filter-actions">
        <el-button type="primary" @click="applyFilters">查询</el-button>
        <el-button @click="resetFilters">重置</el-button>
      </div>
      <span class="result-count">共 {{ total }} 组</span>
    </section>

    <section class="table-card">
      <el-table
        v-loading="loading"
        :data="items"
        border
        stripe
        row-key="pair_key"
        height="calc(100vh - 228px)"
        table-layout="fixed"
        data-testid="relay-wide-table"
      >
        <el-table-column label="寄出 / 收货" width="132" fixed="left">
          <template #default="{ row }">
            <div class="date-cell primary-date">寄 {{ row.planned_ship_date }}</div>
            <div class="date-cell">收 {{ row.planned_receive_date }}</div>
            <el-tag size="small" type="danger" effect="plain">
              重叠 {{ row.overlap_days }} 天
            </el-tag>
          </template>
        </el-table-column>

        <el-table-column label="前一个客户" min-width="250">
          <template #default="{ row }">
            <div class="customer-name">{{ row.predecessor.customer_name || '-' }}</div>
            <div class="secondary">{{ rentalPeriod(row.predecessor) }}</div>
            <div>{{ row.predecessor.customer_phone || '-' }}</div>
            <div class="address" :title="row.predecessor.destination || ''">
              {{ row.predecessor.destination || '-' }}
            </div>
          </template>
        </el-table-column>

        <el-table-column label="后一个客户" min-width="250">
          <template #default="{ row }">
            <div class="customer-name">{{ row.successor.customer_name || '-' }}</div>
            <div class="secondary">{{ rentalPeriod(row.successor) }}</div>
            <div>{{ row.successor.customer_phone || '-' }}</div>
            <div class="address" :title="row.successor.destination || ''">
              {{ row.successor.destination || '-' }}
            </div>
          </template>
        </el-table-column>

        <el-table-column label="设备 / 组合" min-width="230">
          <template #default="{ row }">
            <div class="device-name">
              {{ row.device.model_display_name || row.device.model || '-' }}
              <span>{{ row.device.name || '' }}</span>
            </div>
            <div><b>前：</b>{{ lensText(row.lens_combo) }}</div>
            <div class="secondary accessories">{{ accessoryText(row.accessories) }}</div>
            <div><b>后：</b>{{ lensText(row.successor_lens_combo) }}</div>
            <div class="secondary accessories">{{ accessoryText(row.successor_accessories) }}</div>
            <div
              v-if="relayEquipmentWarningText(row)"
              class="equipment-warning"
              data-testid="equipment-warning"
            >
              <span aria-hidden="true">⚠</span>
              {{ relayEquipmentWarningText(row) }}
            </div>
          </template>
        </el-table-column>

        <el-table-column label="通知文案" min-width="330">
          <template #default="{ row }">
            <div class="relay-notice">
              <el-button
                type="primary"
                size="small"
                plain
                :icon="CopyDocument"
                data-testid="copy-relay-notice"
                @click="copyRelayNotice(row)"
              >
                复制
              </el-button>
              <p class="relay-notice-text" data-testid="relay-notice-text">
                {{ relayNoticeText(row) }}
              </p>
            </div>
          </template>
        </el-table-column>

        <el-table-column label="顺丰物流" min-width="220">
          <template #default="{ row }">
            <template v-if="row.tracking.number">
              <div class="tracking-number">{{ row.tracking.number }}</div>
              <div>{{ row.tracking.summary || row.tracking.status || '暂无物流状态' }}</div>
              <el-button
                v-if="row.case_id"
                link
                type="primary"
                size="small"
                :icon="Refresh"
                @click="refreshOne(row)"
              >
                刷新物流
              </el-button>
            </template>
            <span v-else class="secondary">尚未录入</span>
          </template>
        </el-table-column>

        <el-table-column label="状态" width="112" align="center" fixed="right">
          <template #default="{ row }">
            <el-tag :type="statusType(row.status)">
              {{ statusLabel(row.status) }}
            </el-tag>
            <el-tooltip v-if="row.schedule_changed" content="档期已变化" placement="top">
              <div class="schedule-warning">档期已变化</div>
            </el-tooltip>
          </template>
        </el-table-column>

        <el-table-column label="操作" width="94" align="center" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" :icon="EditPen" @click="editCase(row)">
              维护
            </el-button>
          </template>
        </el-table-column>

        <template #empty>
          <el-empty description="当前范围内没有接力组合" />
        </template>
      </el-table>

      <div class="pagination-row">
        <el-pagination
          v-model:current-page="page"
          v-model:page-size="perPage"
          :total="total"
          :page-sizes="[20, 50, 100]"
          layout="total, sizes, prev, pager, next"
          @current-change="loadCases"
          @size-change="applyFilters"
        />
      </div>
    </section>

    <RelayStatusDialog
      v-model="dialogVisible"
      :relay-case="activeCase"
      @saved="handleSaved"
    />
  </main>
</template>

<style scoped>
.relay-page {
  min-width: 1120px;
  min-height: 100vh;
  padding: 18px 22px;
  color: #1f2937;
  background: #f5f7fa;
}

.page-header,
.title-area,
.filter-bar,
.filter-item,
.filter-actions,
.pagination-row {
  display: flex;
  align-items: center;
}

.page-header {
  justify-content: space-between;
  margin-bottom: 14px;
}

.title-area {
  gap: 12px;
}

h1 {
  margin: 0;
  font-size: 23px;
}

.title-area p {
  margin: 3px 0 0;
  color: #6b7280;
  font-size: 13px;
}

.filter-bar {
  gap: 16px;
  padding: 12px 14px;
  margin-bottom: 12px;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  background: #fff;
}

.filter-item {
  gap: 8px;
}

.filter-label {
  flex: none;
  color: #4b5563;
  font-size: 13px;
  font-weight: 600;
}

.status-filter :deep(.el-select) {
  width: 260px;
}

.date-filter :deep(.el-date-editor) {
  width: 250px;
}

.filter-actions {
  gap: 0;
}

.result-count {
  margin-left: auto;
  color: #6b7280;
  font-size: 13px;
}

.table-card {
  overflow: hidden;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  background: #fff;
}

.date-cell {
  line-height: 22px;
  white-space: nowrap;
}

.primary-date,
.customer-name,
.device-name,
.tracking-number {
  font-weight: 700;
}

.device-name span {
  margin-left: 5px;
  color: #4b5563;
  font-weight: 500;
}

.secondary {
  color: #6b7280;
}

.address,
.accessories {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tracking-number {
  color: #2563eb;
}

.schedule-warning {
  margin-top: 5px;
  color: #d97706;
  font-size: 11px;
  line-height: 1.2;
}

.equipment-warning {
  padding: 4px 6px;
  margin-top: 4px;
  border: 1px solid #f3d19e;
  border-radius: 4px;
  color: #b45309;
  background: #fdf6ec;
  font-size: 11px;
  font-weight: 600;
  line-height: 16px;
  white-space: normal;
}

.equipment-warning span {
  margin-right: 3px;
}

.relay-notice {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 6px;
}

.relay-notice-text {
  margin: 0;
  overflow-wrap: anywhere;
  white-space: normal;
  user-select: text;
  color: #4b5563;
  line-height: 18px;
}

.pagination-row {
  justify-content: flex-end;
  min-height: 52px;
  padding: 8px 14px;
  border-top: 1px solid #e5e7eb;
}

:deep(.el-table .cell) {
  font-size: 12px;
  line-height: 20px;
}
</style>
