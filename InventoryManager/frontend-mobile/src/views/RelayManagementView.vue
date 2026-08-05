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
const statusOptions: Array<{ value: RelayCaseStatus; label: string; shortLabel: string }> = [
  { value: 'pending', label: '待处理', shortLabel: '待处理' },
  { value: 'notified', label: '已通知', shortLabel: '已通知' },
  { value: 'agreed', label: '已同意', shortLabel: '已同意' },
  { value: 'shipped', label: '已寄出', shortLabel: '已寄出' },
  { value: 'completed', label: '已完成', shortLabel: '完成' },
]

const loading = ref(false)
const refreshing = ref(false)
const items = ref<RelayCase[]>([])
const total = ref(0)
const statuses = ref<RelayCaseStatus[]>([...OPEN_STATUSES])
const shipDateFrom = ref(dayjs().subtract(3, 'day').format('YYYY-MM-DD'))
const shipDateTo = ref(dayjs().add(5, 'day').format('YYYY-MM-DD'))
const showDateSheet = ref(false)
const showCalendar = ref(false)
const showStatusSheet = ref(false)
const activeCase = ref<RelayCase | null>(null)

const refreshableIds = computed(() => items.value
  .filter((item) => item.case_id && ['shipped', 'completed'].includes(item.status))
  .map((item) => item.case_id as number))

const defaultCalendarDate = computed<[Date, Date]>(() => [
  dayjs(shipDateFrom.value).toDate(),
  dayjs(shipDateTo.value).toDate(),
])

async function loadCases() {
  if (!statuses.value.length) return
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
    if (statuses.value.length === 1) {
      showToast('请至少保留一个状态')
      return
    }
    statuses.value = statuses.value.filter((value) => value !== status)
  } else {
    statuses.value = statusOptions
      .map((option) => option.value)
      .filter((value) => [...statuses.value, status].includes(value))
  }
  void loadCases()
}

function setDateRange(from: dayjs.ConfigType, to: dayjs.ConfigType) {
  shipDateFrom.value = dayjs(from).format('YYYY-MM-DD')
  shipDateTo.value = dayjs(to).format('YYYY-MM-DD')
  showDateSheet.value = false
  void loadCases()
}

function useDefaultRange() {
  setDateRange(dayjs().subtract(3, 'day'), dayjs().add(5, 'day'))
}

function useNext15Days() {
  setDateRange(dayjs(), dayjs().add(15, 'day'))
}

function openCustomCalendar() {
  showDateSheet.value = false
  showCalendar.value = true
}

function confirmCalendar(values: Date[]) {
  if (values.length !== 2) return
  showCalendar.value = false
  setDateRange(values[0], values[1])
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
    <van-nav-bar title="接力工作台" :border="false" class="relay-nav">
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
          刷新
        </van-button>
      </template>
    </van-nav-bar>

    <section class="mobile-toolbar">
      <div class="toolbar-heading">
        <div>
          <strong>需要处理的接力</strong>
          <span>共 {{ total }} 组</span>
        </div>
        <button
          type="button"
          class="date-filter-button"
          data-testid="relay-date-filter"
          @click="showDateSheet = true"
        >
          <van-icon name="calendar-o" />
          {{ dayjs(shipDateFrom).format('M/D') }}–{{ dayjs(shipDateTo).format('M/D') }}
          <van-icon name="arrow-down" />
        </button>
      </div>

      <div class="status-chip-row" aria-label="状态快捷筛选">
        <button
          v-for="option in statusOptions"
          :key="option.value"
          type="button"
          class="status-chip"
          :class="{ active: statuses.includes(option.value) }"
          :data-testid="`status-chip-${option.value}`"
          @click="toggleStatus(option.value)"
        >
          {{ option.shortLabel }}
        </button>
      </div>
    </section>

    <div class="relay-list">
      <div v-if="loading" class="loading-wrap"><van-loading color="#1677ff" /></div>
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

    <van-action-sheet
      v-model:show="showDateSheet"
      title="寄出时间范围"
      cancel-text="取消"
      class="date-sheet"
    >
      <div class="date-presets">
        <button type="button" data-testid="range-default" @click="useDefaultRange">
          <strong>近期待办</strong>
          <span>T-3 天至 T+5 天</span>
        </button>
        <button type="button" data-testid="range-next-15" @click="useNext15Days">
          <strong>未来 15 天</strong>
          <span>今天至 15 天后</span>
        </button>
        <button type="button" data-testid="range-custom" @click="openCustomCalendar">
          <strong>自定义范围</strong>
          <span>{{ shipDateFrom }} 至 {{ shipDateTo }}</span>
        </button>
      </div>
    </van-action-sheet>

    <van-calendar
      v-model:show="showCalendar"
      type="range"
      title="选择寄出时间范围"
      :default-date="defaultCalendarDate"
      :min-date="dayjs().subtract(1, 'year').toDate()"
      :max-date="dayjs().add(2, 'year').toDate()"
      color="#1677ff"
      @confirm="confirmCalendar"
    />

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
  background: #f2f4f7;
}

.relay-nav {
  --van-nav-bar-title-font-size: 18px;
}

.relay-nav :deep(.van-button) {
  min-width: 72px;
  min-height: 36px;
  border-radius: 8px;
}

.mobile-toolbar {
  position: sticky;
  z-index: 4;
  top: 0;
  padding: 10px 12px 9px;
  border-bottom: 1px solid #e6e8eb;
  background: #fff;
  box-shadow: 0 2px 8px rgb(31 41 55 / 4%);
}

.toolbar-heading,
.toolbar-heading > div,
.date-filter-button,
.status-chip-row {
  display: flex;
  align-items: center;
}

.toolbar-heading {
  justify-content: space-between;
  gap: 12px;
}

.toolbar-heading > div {
  min-width: 0;
  flex-direction: column;
  align-items: flex-start;
}

.toolbar-heading strong {
  font-size: 14px;
}

.toolbar-heading span {
  margin-top: 2px;
  color: #8a8f98;
  font-size: 11px;
}

.date-filter-button {
  min-height: 44px;
  flex: none;
  gap: 5px;
  padding: 0 10px;
  border: 1px solid #d9e6f7;
  border-radius: 9px;
  color: #1668dc;
  background: #f5f9ff;
  font-size: 12px;
  font-weight: 600;
}

.status-chip-row {
  gap: 7px;
  margin-top: 10px;
  overflow-x: auto;
  scrollbar-width: none;
}

.status-chip-row::-webkit-scrollbar {
  display: none;
}

.status-chip {
  min-width: 63px;
  min-height: 44px;
  flex: 1 0 auto;
  padding: 0 10px;
  border: 1px solid #e1e4e8;
  border-radius: 19px;
  color: #6b7280;
  background: #f8f9fa;
  font-size: 12px;
}

.status-chip.active {
  border-color: #1677ff;
  color: #fff;
  background: #1677ff;
  box-shadow: 0 2px 6px rgb(22 119 255 / 18%);
  font-weight: 600;
}

.relay-list {
  height: calc(100% - 151px);
  overflow-y: auto;
  padding: 12px 10px calc(66px + env(safe-area-inset-bottom));
  -webkit-overflow-scrolling: touch;
}

.loading-wrap {
  display: flex;
  min-height: 180px;
  align-items: center;
  justify-content: center;
}

.date-sheet {
  padding-bottom: calc(10px + env(safe-area-inset-bottom));
}

.date-presets {
  padding: 4px 14px 12px;
}

.date-presets button {
  display: flex;
  width: 100%;
  min-height: 58px;
  flex-direction: column;
  align-items: flex-start;
  justify-content: center;
  padding: 8px 12px;
  border: 0;
  border-bottom: 1px solid #f0f1f3;
  background: #fff;
  text-align: left;
}

.date-presets strong {
  color: #202124;
  font-size: 15px;
}

.date-presets span {
  margin-top: 3px;
  color: #8a8f98;
  font-size: 12px;
}
</style>
