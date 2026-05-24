<template>
  <div class="gantt-view">
    <!-- 导航栏 -->
    <van-nav-bar title="甘特图" :border="false">
      <template #left>
        <van-button size="small" icon="arrow-left" @click="shiftWindow(-7)" plain />
        <span class="date-range-label">{{ windowLabel }}</span>
        <van-button size="small" icon="arrow" @click="shiftWindow(7)" plain />
      </template>
      <template #right>
        <van-button
          size="small"
          :type="selectedModel ? 'primary' : 'default'"
          plain
          style="margin-right: 6px"
          @click="showModelFilter = true"
        >{{ selectedModel || '筛选' }}</van-button>
        <van-button
          size="small"
          icon="search"
          plain
          style="margin-right: 4px"
          @click="router.push({ name: 'search' })"
        />
        <van-button
          size="small"
          icon="setting-o"
          plain
          style="margin-right: 4px"
          @click="router.push({ name: 'device-status' })"
        />
        <van-button
          size="small"
          type="primary"
          icon="plus"
          @click="goCreate"
        >新建</van-button>
      </template>
    </van-nav-bar>

    <!-- 甘特图表格 -->
    <GanttGrid
      :devices="filteredDevices"
      :rentals="ganttStore.rentals"
      :window-start="windowStart"
      :loading="ganttStore.loading"
      :daily-stats="dailyStats"
      @bar-click="openSheet"
    />

    <!-- 底部详情弹窗 -->
    <RentalBottomSheet
      v-model="sheetVisible"
      :rental="selectedRental"
      @deleted="onDeleted"
    />

    <!-- 型号筛选 action sheet -->
    <van-action-sheet
      v-model:show="showModelFilter"
      :actions="modelFilterActions"
      cancel-text="取消"
      @select="onModelSelect"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import dayjs from 'dayjs'
import axios from 'axios'
import { useGanttStore } from '@/stores/gantt'
import type { Rental } from '@/stores/gantt'
import GanttGrid from '@/components/GanttGrid.vue'
import RentalBottomSheet from '@/components/RentalBottomSheet.vue'

const router = useRouter()
const ganttStore = useGanttStore()

// 窗口起始日期：今天 -2 天
const windowOffset = ref(0) // 以7天为单位的偏移
const windowStart = computed(() => {
  return dayjs().subtract(2, 'day').add(windowOffset.value * 7, 'day').format('YYYY-MM-DD')
})

const windowLabel = computed(() => {
  const start = dayjs(windowStart.value)
  const end = start.add(13, 'day')
  return `${start.format('M/D')}~${end.format('M/D')}`
})

const sheetVisible = ref(false)
const selectedRental = ref<Rental | null>(null)

// 每日统计数据
const dailyStats = ref<Record<string, { available_count: number; ship_out_count: number; accessory_ship_out_count: number }>>({})

const DAYS = 14

const fetchDailyStats = async () => {
  const start = dayjs(windowStart.value)
  const dates = Array.from({ length: DAYS }, (_, i) => start.add(i, 'day').format('YYYY-MM-DD'))
  const results = await Promise.allSettled(
    dates.map(date => axios.get('/api/gantt/daily-stats', { params: { date } }))
  )
  const stats: typeof dailyStats.value = {}
  results.forEach((result, i) => {
    if (result.status === 'fulfilled' && result.value.data?.success) {
      stats[dates[i]] = result.value.data.data
    }
  })
  dailyStats.value = stats
}

const shiftWindow = (days: number) => {
  windowOffset.value += days / 7
  ganttStore.loadData()
  fetchDailyStats()
}

const openSheet = (rental: Rental) => {
  selectedRental.value = rental
  sheetVisible.value = true
}

const onDeleted = () => {
  ganttStore.loadData()
  fetchDailyStats()
}

const goCreate = () => {
  router.push({ name: 'create-rental' })
}

// ── 型号筛选 ──────────────────────────────────────────
const selectedModel = ref<string | null>(null)
const showModelFilter = ref(false)

const availableModels = computed(() => {
  const models = new Set(ganttStore.availableDevices.map(d => d.model).filter(Boolean))
  return Array.from(models).sort()
})

const modelFilterActions = computed(() => [
  { name: '全部型号', value: null },
  ...availableModels.value.map(m => ({ name: m, value: m }))
])

const onModelSelect = (action: { name: string; value: string | null }) => {
  selectedModel.value = action.value
  showModelFilter.value = false
}

const filteredDevices = computed(() => {
  if (!selectedModel.value) return ganttStore.availableDevices
  return ganttStore.availableDevices.filter(d => d.model === selectedModel.value)
})

onMounted(() => {
  ganttStore.loadData()
  fetchDailyStats()
})
</script>

<style scoped>
.gantt-view {
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* 导航栏内布局 */
:deep(.van-nav-bar__left) {
  display: flex;
  align-items: center;
  gap: 4px;
}

.date-range-label {
  font-size: 12px;
  color: #333;
  white-space: nowrap;
}

/* 让甘特表格占满剩余高度 */
.gantt-view > :deep(.gantt-grid) {
  flex: 1;
  overflow: hidden;
}
</style>
