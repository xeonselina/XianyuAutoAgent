<template>
  <div class="gantt-grid" ref="gridRef">
    <!-- 表头行 -->
    <div class="gantt-header">
      <div class="device-col header-cell">设备</div>
      <div class="dates-cols">
        <div
          v-for="date in dateColumns"
          :key="date.key"
          class="date-cell"
          :class="{ today: date.isToday, weekend: date.isWeekend }"
        >
          <span class="date-num">{{ date.day }}</span>
          <span class="date-week">{{ date.week }}</span>
        </div>
      </div>
    </div>

    <!-- 设备行列表 -->
    <div class="gantt-body" ref="bodyRef">
      <div v-if="loading" class="loading-wrap">
        <van-loading color="#409eff" size="24" />
        <span>加载中...</span>
      </div>

      <div v-else-if="!devices.length" class="empty-wrap">
        <van-empty description="暂无设备数据" />
      </div>

      <template v-else>
        <div
          v-for="device in devices"
          :key="device.id"
          class="gantt-row"
        >
          <!-- 设备名称列 -->
          <div class="device-col row-device-cell">
            <span class="device-name">{{ device.name }}</span>
          </div>

          <!-- 日期格子 -->
          <div class="dates-cols row-dates-area">
            <!-- 背景格子（网格线） -->
            <div
              v-for="date in dateColumns"
              :key="date.key"
              class="date-bg-cell"
              :class="{ today: date.isToday }"
            />

            <!-- 租赁条 -->
            <template v-for="rental in getRentalsForDevice(device.id)" :key="rental.id">
              <!-- 租赁期条（上条） -->
              <div
                v-if="getRentalBarStyle(rental, 'rental')"
                class="rental-bar rental-bar--upper"
                :style="getRentalBarStyle(rental, 'rental')"
                @click.stop="$emit('bar-click', rental)"
              >
                <span class="bar-label">{{ rental.customer_name }}</span>
              </div>

              <!-- 物流期条（下条），仅 ship_out_time 和 ship_in_time 都存在时才显示 -->
              <div
                v-if="rental.ship_out_time && rental.ship_in_time && getRentalBarStyle(rental, 'logistics')"
                class="rental-bar rental-bar--lower"
                :style="getRentalBarStyle(rental, 'logistics')"
              >
                <span class="bar-label">物流</span>
              </div>
            </template>
          </div>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import dayjs from 'dayjs'
import type { Device, Rental } from '@/stores/gantt'

const props = defineProps<{
  devices: Device[]
  rentals: Rental[]
  windowStart: string   // YYYY-MM-DD
  loading: boolean
}>()

const emit = defineEmits<{
  (e: 'bar-click', rental: Rental): void
}>()

const gridRef = ref<HTMLElement>()
const bodyRef = ref<HTMLElement>()

// 设备列宽 54px，固定
const DEVICE_COL_WIDTH = 54
// 日期列数，固定14
const DAYS = 14

/** 14天日期列数据 */
const dateColumns = computed(() => {
  return Array.from({ length: DAYS }, (_, i) => {
    const d = dayjs(props.windowStart).add(i, 'day')
    return {
      key: d.format('YYYY-MM-DD'),
      day: d.date(),
      week: ['日', '一', '二', '三', '四', '五', '六'][d.day()],
      isToday: d.isSame(dayjs(), 'day'),
      isWeekend: d.day() === 0 || d.day() === 6,
      date: d
    }
  })
})

/** 每列宽度（百分比，相对 dates-cols 区域） */
const colWidthPct = computed(() => `${100 / DAYS}%`)

/** 获取某设备的租赁列表 */
const getRentalsForDevice = (deviceId: number) => {
  return props.rentals.filter(r => r.device_id === deviceId)
}

/**
 * 计算租赁条的 CSS position style
 * type: 'rental' | 'logistics'
 */
const getRentalBarStyle = (rental: Rental, type: 'rental' | 'logistics') => {
  const windowStartDay = dayjs(props.windowStart).startOf('day')
  const windowEndDay = windowStartDay.add(DAYS - 1, 'day').endOf('day')

  let barStart: dayjs.Dayjs
  let barEnd: dayjs.Dayjs

  if (type === 'rental') {
    barStart = dayjs(rental.start_date).startOf('day')
    barEnd = dayjs(rental.end_date).startOf('day')
  } else {
    if (!rental.ship_out_time || !rental.ship_in_time) return null
    barStart = dayjs(rental.ship_out_time).startOf('day')
    barEnd = dayjs(rental.ship_in_time).startOf('day')
  }

  // 如果完全不在窗口内，不显示
  if (barEnd.isBefore(windowStartDay) || barStart.isAfter(windowEndDay)) return null

  // 裁剪到窗口范围
  const clippedStart = barStart.isBefore(windowStartDay) ? windowStartDay : barStart
  const clippedEnd = barEnd.isAfter(windowEndDay) ? windowEndDay : barEnd

  const startOffset = clippedStart.diff(windowStartDay, 'day')
  const durationDays = clippedEnd.diff(clippedStart, 'day') + 1

  const left = `${(startOffset / DAYS) * 100}%`
  const width = `calc(${(durationDays / DAYS) * 100}% - 2px)`

  if (type === 'rental') {
    return { left, width, top: '3px', height: '9px' }
  } else {
    return { left, width, top: '14px', height: '7px' }
  }
}
</script>

<style scoped>
.gantt-grid {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
  background: #fff;
}

/* 表头 */
.gantt-header {
  display: flex;
  height: 36px;
  border-bottom: 1px solid #e8e8e8;
  flex-shrink: 0;
  background: #fafafa;
  position: sticky;
  top: 0;
  z-index: 10;
}

.device-col {
  width: v-bind(DEVICE_COL_WIDTH + 'px');
  min-width: v-bind(DEVICE_COL_WIDTH + 'px');
  flex-shrink: 0;
  border-right: 1px solid #e8e8e8;
}

.header-cell {
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 10px;
  color: #666;
  font-weight: 500;
}

.dates-cols {
  flex: 1;
  display: flex;
}

.date-cell {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  font-size: 9px;
  border-right: 1px solid #eee;
}

.date-cell:last-child { border-right: none; }

.date-cell.today {
  background: #e6f4ff;
}

.date-cell.weekend {
  background: #fef9f0;
}

.date-num {
  font-size: 10px;
  font-weight: 600;
  color: #333;
  line-height: 1.2;
}

.date-week {
  font-size: 8px;
  color: #999;
  line-height: 1.2;
}

/* 甘特主体 */
.gantt-body {
  flex: 1;
  overflow-y: auto;
  -webkit-overflow-scrolling: touch;
}

.loading-wrap,
.empty-wrap {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 40px 0;
  gap: 8px;
  color: #999;
  font-size: 12px;
}

/* 每行 */
.gantt-row {
  display: flex;
  height: 26px;
  border-bottom: 1px solid #f0f0f0;
}

.row-device-cell {
  display: flex;
  align-items: center;
  padding: 0 2px;
  overflow: hidden;
}

.device-name {
  font-size: 7px;
  color: #333;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  width: 100%;
}

.row-dates-area {
  position: relative;
  flex: 1;
}

/* 背景格子 */
.date-bg-cell {
  position: absolute;
  top: 0;
  bottom: 0;
  width: v-bind(colWidthPct);
  border-right: 1px solid #f5f5f5;
}

.date-bg-cell:nth-child(1)  { left: 0 }
.date-bg-cell:nth-child(2)  { left: calc(1 * v-bind(colWidthPct)) }
.date-bg-cell:nth-child(3)  { left: calc(2 * v-bind(colWidthPct)) }
.date-bg-cell:nth-child(4)  { left: calc(3 * v-bind(colWidthPct)) }
.date-bg-cell:nth-child(5)  { left: calc(4 * v-bind(colWidthPct)) }
.date-bg-cell:nth-child(6)  { left: calc(5 * v-bind(colWidthPct)) }
.date-bg-cell:nth-child(7)  { left: calc(6 * v-bind(colWidthPct)) }
.date-bg-cell:nth-child(8)  { left: calc(7 * v-bind(colWidthPct)) }
.date-bg-cell:nth-child(9)  { left: calc(8 * v-bind(colWidthPct)) }
.date-bg-cell:nth-child(10) { left: calc(9 * v-bind(colWidthPct)) }
.date-bg-cell:nth-child(11) { left: calc(10 * v-bind(colWidthPct)) }
.date-bg-cell:nth-child(12) { left: calc(11 * v-bind(colWidthPct)) }
.date-bg-cell:nth-child(13) { left: calc(12 * v-bind(colWidthPct)) }
.date-bg-cell:nth-child(14) { left: calc(13 * v-bind(colWidthPct)) }

.date-bg-cell.today {
  background: rgba(64, 158, 255, 0.05);
}

/* 租赁条 */
.rental-bar {
  position: absolute;
  border-radius: 2px;
  overflow: hidden;
  cursor: pointer;
  display: flex;
  align-items: center;
  padding: 0 2px;
}

.rental-bar--upper {
  background: #409eff;
}

.rental-bar--lower {
  background: #a0cfff;
}

.bar-label {
  font-size: 6px;
  color: #fff;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  line-height: 1;
}
</style>
