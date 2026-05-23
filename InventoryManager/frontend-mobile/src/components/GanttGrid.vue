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

            <!-- 租赁条（双层：外层半透明物流期 + 内层实色租赁期） -->
            <template v-for="rental in getRentalsForDevice(device.id)" :key="rental.id">
              <!-- 外层半透明条：ship_out_time → ship_in_time -->
              <div
                v-if="getShipRangeBarStyle(rental)"
                class="rental-bar ship-range-bar"
                :style="getShipRangeBarStyle(rental)!"
              />
              <!-- 内层实色条：start_date → end_date -->
              <div
                v-if="getRentalPeriodBarStyle(rental)"
                class="rental-bar rental-period-bar"
                :style="getRentalPeriodBarStyle(rental)!"
                @click.stop="$emit('bar-click', rental)"
              >
                <span class="bar-label">{{ rental.customer_name }}</span>
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

/** 随机颜色（按 rentalId 确定性选取） */
const generateRandomColor = (rentalId: number): string => {
  const colors = [
    '#f44336', '#e91e63', '#9c27b0', '#673ab7', '#3f51b5',
    '#2196f3', '#03a9f4', '#00bcd4', '#009688', '#4caf50',
    '#8bc34a', '#cddc39', '#ffc107', '#ff9800', '#ff5722',
    '#795548', '#607d8b', '#e53935', '#d81b60', '#8e24aa',
    '#5e35b1', '#3949ab', '#1e88e5', '#039be5', '#00acc1',
    '#00897b', '#43a047', '#7cb342', '#c0ca33', '#ffb300',
    '#fb8c00', '#f4511e', '#6d4c41', '#546e7a', '#c62828',
    '#ad1457', '#6a1b9a', '#4527a0', '#283593', '#1565c0',
    '#0277bd', '#00838f', '#00695c', '#2e7d32', '#558b2f',
    '#9e9d24', '#f9a825', '#ff6f00', '#e65100', '#bf360c',
    '#4e342e', '#37474f', '#b71c1c', '#880e4f', '#4a148c',
    '#311b92', '#1a237e', '#0d47a1', '#01579b', '#006064',
    '#004d40', '#1b5e20', '#33691e', '#827717', '#f57f17',
    '#ff6d00', '#dd2c00', '#3e2723', '#263238', '#d32f2f',
    '#c2185b', '#7b1fa2', '#512da8', '#303f9f', '#0288d1'
  ]
  return colors[rentalId % colors.length]
}

const hexToRgba = (hex: string, alpha: number): string => {
  const r = parseInt(hex.slice(1, 3), 16)
  const g = parseInt(hex.slice(3, 5), 16)
  const b = parseInt(hex.slice(5, 7), 16)
  return `rgba(${r}, ${g}, ${b}, ${alpha})`
}

/** 获取某设备的租赁列表（包含 ship_out_time 在窗口内的记录） */
const getRentalsForDevice = (deviceId: number) => {
  const windowStartDay = dayjs(props.windowStart).startOf('day')
  const windowEndDay = windowStartDay.add(DAYS - 1, 'day').endOf('day')

  return props.rentals.filter(r => {
    if (r.device_id !== deviceId) return false
    // 外层条范围：ship_out_time → ship_in_time（如有），否则 start_date → end_date
    const barStart = r.ship_out_time ? dayjs(r.ship_out_time).startOf('day') : dayjs(r.start_date).startOf('day')
    const barEnd   = r.ship_in_time  ? dayjs(r.ship_in_time).startOf('day')  : dayjs(r.end_date).startOf('day')
    return barEnd.isAfter(windowStartDay) && barStart.isBefore(windowEndDay.add(1, 'day'))
  })
}

/**
 * 外层半透明条：ship_out_time → ship_in_time（无则 start_date → end_date）
 */
const getShipRangeBarStyle = (rental: Rental) => {
  const windowStartDay = dayjs(props.windowStart).startOf('day')
  const windowEndDay = windowStartDay.add(DAYS - 1, 'day').endOf('day')

  const barStart = rental.ship_out_time ? dayjs(rental.ship_out_time).startOf('day') : dayjs(rental.start_date).startOf('day')
  const barEnd   = rental.ship_in_time  ? dayjs(rental.ship_in_time).startOf('day')  : dayjs(rental.end_date).startOf('day')

  if (barEnd.isBefore(windowStartDay) || barStart.isAfter(windowEndDay)) return null

  const clippedStart = barStart.isBefore(windowStartDay) ? windowStartDay : barStart
  const clippedEnd   = barEnd.isAfter(windowEndDay)       ? windowEndDay   : barEnd

  const startOffset  = clippedStart.diff(windowStartDay, 'day')
  const durationDays = clippedEnd.diff(clippedStart, 'day') + 1

  const left  = `${(startOffset / DAYS) * 100}%`
  const width = `calc(${(durationDays / DAYS) * 100}% - 2px)`
  const color = generateRandomColor(rental.id)

  return {
    left,
    width,
    top: '2px',
    height: '22px',
    background: hexToRgba(color, 0.22),
    border: `1px solid ${hexToRgba(color, 0.4)}`,
    zIndex: 1,
  }
}

/**
 * 内层实色条：start_date → end_date，绝对定位
 */
const getRentalPeriodBarStyle = (rental: Rental) => {
  const windowStartDay = dayjs(props.windowStart).startOf('day')
  const windowEndDay = windowStartDay.add(DAYS - 1, 'day').endOf('day')

  const startDate = dayjs(rental.start_date).startOf('day')
  const endDate   = dayjs(rental.end_date).startOf('day')

  if (endDate.isBefore(windowStartDay) || startDate.isAfter(windowEndDay)) return null

  const clippedStart = startDate.isBefore(windowStartDay) ? windowStartDay : startDate
  const clippedEnd   = endDate.isAfter(windowEndDay)       ? windowEndDay   : endDate

  const startOffset  = clippedStart.diff(windowStartDay, 'day')
  const durationDays = clippedEnd.diff(clippedStart, 'day') + 1

  const left  = `${(startOffset / DAYS) * 100}%`
  const width = `calc(${(durationDays / DAYS) * 100}% - 2px)`
  const color = generateRandomColor(rental.id)

  return {
    left,
    width,
    top: '2px',
    height: '22px',
    background: color,
    zIndex: 2,
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

/* 租赁条（通用） */
.rental-bar {
  position: absolute;
  border-radius: 2px;
  overflow: hidden;
}

/* 外层半透明条（物流期） */
.ship-range-bar {
  cursor: default;
}

/* 内层实色条（租赁期） */
.rental-period-bar {
  cursor: pointer;
  display: flex;
  align-items: center;
  padding: 0 2px;
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
