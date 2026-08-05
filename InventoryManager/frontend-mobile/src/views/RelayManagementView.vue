<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import dayjs from 'dayjs'
import { showFailToast, showSuccessToast, showToast } from 'vant'

import {
  listRelayCases,
  refreshRelayTracking,
  refreshRelayTrackingBatch,
} from '@/api/relayCases'
import RelayCaseCard from '@/components/RelayCaseCard.vue'
import RelayStatusSheet from '@/components/RelayStatusSheet.vue'
import type { RelayCase, RelayCaseStatus } from '@/types/relayCase'

defineOptions({ name: 'RelayManagementView' })

const OPEN_STATUSES: RelayCaseStatus[] = ['pending', 'notified', 'agreed', 'shipped']
const statusOptions: Array<{ value: RelayCaseStatus; label: string }> = [
  { value: 'pending', label: '待处理' },
  { value: 'notified', label: '已通知' },
  { value: 'agreed', label: '已同意' },
  { value: 'shipped', label: '已寄出' },
  { value: 'completed', label: '已完成' },
]

const loading = ref(false)
const refreshing = ref(false)
const items = ref<RelayCase[]>([])
const total = ref(0)
const statuses = ref<RelayCaseStatus[]>([...OPEN_STATUSES])
const shipDateFrom = ref(dayjs().subtract(3, 'day').format('YYYY-MM-DD'))
const shipDateTo = ref(dayjs().add(5, 'day').format('YYYY-MM-DD'))
const showFilters = ref(false)
const showStatusSheet = ref(false)
const activeCase = ref<RelayCase | null>(null)

const statusSummary = computed(() => {
  if (statuses.value.length === statusOptions.length) return '全部状态'
  return statusOptions
    .filter((option) => statuses.value.includes(option.value))
    .map((option) => option.label)
    .join('、') || '未选状态'
})

const refreshableIds = computed(() => items.value
  .filter((item) => item.case_id && ['shipped', 'completed'].includes(item.status))
  .map((item) => item.case_id as number))

async function loadCases() {
  if (!statuses.value.length) {
    items.value = []
    total.value = 0
    return
  }
  loading.value = true
  try {
    const result = await listRelayCases({
      statuses: statuses.value,
      shipDateFrom: shipDateFrom.value,
      shipDateTo: shipDateTo.value,
      page: 1,
      perPage: 50,
    })
    items.value = result.items
    total.value = result.total
  } catch (error) {
    showFailToast(error instanceof Error ? error.message : '加载接力列表失败')
  } finally {
    loading.value = false
  }
}

function toggleStatus(status: RelayCaseStatus) {
  if (statuses.value.includes(status)) {
    statuses.value = statuses.value.filter((value) => value !== status)
  } else {
    statuses.value = [...statuses.value, status]
  }
}

function applyFilters() {
  if (!statuses.value.length) {
    showToast('请至少选择一个状态')
    return
  }
  if (!shipDateFrom.value || !shipDateTo.value || shipDateFrom.value > shipDateTo.value) {
    showToast('请选择有效的寄出时间范围')
    return
  }
  showFilters.value = false
  void loadCases()
}

function resetFilters() {
  statuses.value = [...OPEN_STATUSES]
  shipDateFrom.value = dayjs().subtract(3, 'day').format('YYYY-MM-DD')
  shipDateTo.value = dayjs().add(5, 'day').format('YYYY-MM-DD')
}

function maintain(relayCase: RelayCase) {
  activeCase.value = relayCase
  showStatusSheet.value = true
}

async function refreshOne(relayCase: RelayCase) {
  if (!relayCase.case_id) return
  try {
    await refreshRelayTracking(relayCase.case_id)
    showSuccessToast('物流状态已刷新')
    await loadCases()
  } catch (error) {
    showFailToast(error instanceof Error ? error.message : '物流刷新失败')
  }
}

async function refreshAll() {
  if (!refreshableIds.value.length) {
    showToast('当前页没有可刷新的顺丰运单')
    return
  }
  refreshing.value = true
  try {
    const result = await refreshRelayTrackingBatch(refreshableIds.value)
    showSuccessToast(`已刷新 ${result.success_count}/${result.total} 条`)
    await loadCases()
  } catch (error) {
    showFailToast(error instanceof Error ? error.message : '批量刷新失败')
  } finally {
    refreshing.value = false
  }
}

function saved() {
  void loadCases()
}

onMounted(loadCases)
</script>

<template>
  <div class="relay-view">
    <van-nav-bar title="接力管理" :border="false">
      <template #right>
        <van-button
          icon="replay"
          size="small"
          plain
          type="primary"
          :loading="refreshing"
          :disabled="!refreshableIds.length"
          data-testid="relay-refresh-all"
          @click="refreshAll"
        >
          刷新物流
        </van-button>
      </template>
    </van-nav-bar>

    <button type="button" class="filter-summary" @click="showFilters = true">
      <div>
        <strong>{{ statusSummary }}</strong>
        <span>寄出时间 {{ shipDateFrom }} 至 {{ shipDateTo }}</span>
      </div>
      <div class="filter-count">{{ total }} 组 <van-icon name="filter-o" /></div>
    </button>

    <div class="relay-list">
      <div v-if="loading" class="loading-wrap"><van-loading color="#1989fa" /></div>
      <van-empty v-else-if="!items.length" description="当前范围内没有接力组合" />
      <template v-else>
        <RelayCaseCard
          v-for="relayCase in items"
          :key="relayCase.pair_key"
          :relay-case="relayCase"
          @maintain="maintain"
          @refresh="refreshOne"
        />
      </template>
    </div>

    <van-popup
      v-model:show="showFilters"
      position="bottom"
      round
      closeable
      class="filter-popup"
    >
      <h2>筛选接力单</h2>
      <div class="filter-section">
        <div class="section-label">状态（可多选）</div>
        <div class="status-options">
          <button
            v-for="option in statusOptions"
            :key="option.value"
            type="button"
            :class="{ active: statuses.includes(option.value) }"
            @click="toggleStatus(option.value)"
          >
            {{ option.label }}
          </button>
        </div>
      </div>
      <div class="filter-section">
        <div class="section-label">寄出时间范围</div>
        <div class="date-inputs">
          <input v-model="shipDateFrom" type="date">
          <span>至</span>
          <input v-model="shipDateTo" type="date">
        </div>
      </div>
      <div class="filter-buttons">
        <van-button block @click="resetFilters">重置</van-button>
        <van-button block type="primary" @click="applyFilters">查询</van-button>
      </div>
    </van-popup>

    <RelayStatusSheet
      v-model="showStatusSheet"
      :relay-case="activeCase"
      @saved="saved"
    />
  </div>
</template>

<style scoped>
.relay-view {
  height: 100%;
  overflow: hidden;
  background: #f5f6f8;
}

.filter-summary {
  display: flex;
  width: 100%;
  min-height: 58px;
  align-items: center;
  justify-content: space-between;
  padding: 8px 14px;
  border: 0;
  border-bottom: 1px solid #ebedf0;
  background: #fff;
  color: #323233;
  text-align: left;
}

.filter-summary div:first-child {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 3px;
}

.filter-summary strong {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
}

.filter-summary span,
.filter-count {
  color: #969799;
  font-size: 11px;
}

.filter-count {
  flex: none;
  margin-left: 10px;
}

.relay-list {
  height: calc(100% - 104px);
  overflow-y: auto;
  padding: 12px 10px calc(64px + env(safe-area-inset-bottom));
  -webkit-overflow-scrolling: touch;
}

.loading-wrap {
  display: flex;
  min-height: 180px;
  align-items: center;
  justify-content: center;
}

.filter-popup {
  padding: 16px 16px calc(18px + env(safe-area-inset-bottom));
}

.filter-popup h2 {
  margin: 2px 0 20px;
  font-size: 18px;
  text-align: center;
}

.filter-section {
  margin-bottom: 20px;
}

.section-label {
  margin-bottom: 9px;
  color: #646566;
  font-size: 13px;
}

.status-options {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
}

.status-options button {
  min-height: 44px;
  border: 1px solid #dcdee0;
  border-radius: 8px;
  background: #fff;
}

.status-options button.active {
  border-color: #1989fa;
  color: #1989fa;
  background: #edf7ff;
}

.date-inputs,
.filter-buttons {
  display: flex;
  align-items: center;
  gap: 8px;
}

.date-inputs input {
  min-width: 0;
  min-height: 44px;
  flex: 1;
  padding: 0 8px;
  border: 1px solid #dcdee0;
  border-radius: 8px;
  background: #fff;
  font-size: 13px;
}

.filter-buttons :deep(.van-button) {
  min-height: 46px;
}
</style>
