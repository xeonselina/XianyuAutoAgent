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
          type="primary"
          icon="plus"
          @click="goCreate"
        >新建</van-button>
      </template>
    </van-nav-bar>

    <!-- 甘特图表格 -->
    <GanttGrid
      :devices="ganttStore.availableDevices"
      :rentals="ganttStore.rentals"
      :window-start="windowStart"
      :loading="ganttStore.loading"
      @bar-click="openSheet"
    />

    <!-- 底部详情弹窗 -->
    <RentalBottomSheet
      v-model="sheetVisible"
      :rental="selectedRental"
      @deleted="onDeleted"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import dayjs from 'dayjs'
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

const shiftWindow = (days: number) => {
  windowOffset.value += days / 7
  ganttStore.loadData()
}

const openSheet = (rental: Rental) => {
  selectedRental.value = rental
  sheetVisible.value = true
}

const onDeleted = () => {
  ganttStore.loadData()
}

const goCreate = () => {
  router.push({ name: 'create-rental' })
}

onMounted(() => {
  ganttStore.loadData()
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
