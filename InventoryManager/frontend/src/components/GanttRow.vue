<template>
  <div class="gantt-row">
    <div class="device-cell" :class="[`device-status-${device.status}`, `device-lifecycle-${device.lifecycle_status || 'active'}`]">
      <div class="device-info">
        <div class="device-name">{{ device.name }}</div>
        <div class="device-details">
          <span class="device-sn">{{ device.serial_number }}</span>
        </div>
        <div class="device-lifecycle">
          <el-select
            :model-value="device.lifecycle_status || 'active'"
            size="small"
            style="width: 100px;"
            @change="updateLifecycleStatus"
          >
            <el-option label="🟢 使用中" value="active" />
            <el-option label="💰 已售出" value="sold" />
            <el-option label="🔧 已损坏" value="damaged" />
            <el-option label="⛔ 已停用" value="decommissioned" />
            <el-option label="📦 已退役" value="retired" />
          </el-select>
        </div>
      </div>
    </div>

    <div
      v-for="date in dates"
      :key="date.toString()"
      class="date-cell"
      :class="{
        'is-today': isToday(date),
        'is-weekend': isWeekend(date),
        'is-empty': isDateEmpty(date)
      }"
    >
      <!-- 外层半透明条：跨越 ship_out_time → ship_in_time -->
      <div
        v-for="rental in getRentalsForDate(date)"
        :key="`rental-${rental.id}`"
        v-show="shouldShowRentalBar(rental, date)"
        class="rental-bar"
        :style="getShipRangeStyle(rental, date)"
        @click="$emit('edit-rental', rental)"
        @dblclick="$emit('delete-rental', rental)"
        @mouseenter="handleRentalHover(rental, $event)"
        @mouseleave="handleRentalLeave"
      >
        <!-- 内层实色条：跨越 start_date → end_date -->
        <div
          class="rental-period"
          :style="getRentalPeriodStyle(rental, date)"
        >
          <div class="rental-content">
            <div class="rental-customer-line">
              <span class="rental-customer">
                <span v-if="rental.status === 'shipped'" class="status-icon shipped-icon">🚀</span>
                <span v-else-if="rental.status === 'returned'" class="status-icon returned-icon">✅</span>
                <span v-else-if="rental.status === 'not_shipped'" class="status-icon">📦</span>
                {{ rental.customer_name }}
              </span>
              <el-icon v-if="hasAccessories(rental)" class="accessory-icon" title="包含附件">
                <Tools />
              </el-icon>
            </div>
            <span class="rental-phone">{{ rental.customer_phone }}</span>
          </div>

          <!-- 档期冲突警告图标 -->
          <span
            v-if="rentalConflicts.get(rental.id)?.hasConflict"
            class="conflict-warning-icon"
            @click.stop="showConflictDetails(rental)"
            title="档期冲突警告"
          >
            ⚠️
          </span>
        </div>
      </div>
    </div>
    
    <!-- Tooltip组件 -->
    <RentalTooltip
      :rental="hoveredRental"
      :visible="tooltipVisible"
      :trigger-ref="tooltipTriggerRef"
      :conflict-info="currentRentalConflictInfo"
      @tooltip-enter="handleTooltipEnter"
      @tooltip-leave="handleTooltipLeave"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, defineAsyncComponent, onUnmounted } from 'vue'
import type { Device, Rental } from '../stores/gantt'
import {
  toDateString,
  parseDate,
  isToday
} from '@/utils/dateUtils'
import dayjs from 'dayjs'
import { Tools } from '@element-plus/icons-vue'

// Weekend detection function
const isWeekend = (date: Date) => {
  const day = date.getDay()
  return day === 0 || day === 6
}

const RentalTooltip = defineAsyncComponent(() => import('./RentalTooltip.vue'))

interface Props {
  device: Device
  rentals: Rental[]
  dates: Date[]
}

interface ConflictInfo {
  hasConflict: boolean
  nextRentalId?: number
  dayGap?: number
  currentDestination?: string
  nextDestination?: string
}

const props = defineProps<Props>()

const emit = defineEmits<{
  'edit-rental': [rental: Rental]
  'delete-rental': [rental: Rental]
  'update-device-status': [device: Device, newStatus: string]
  'update-device-lifecycle': [device: Device, newLifecycle: string]
}>()

// Tooltip相关状态
const hoveredRental = ref<Rental | null>(null)
const tooltipVisible = ref(false)
const tooltipTriggerRef = ref<HTMLElement>()
let showTimer: number | null = null
let hideTimer: number | null = null

// 更新设备状态
const updateDeviceStatus = (newStatus: string) => {
  emit('update-device-status', props.device, newStatus)
}

// 更新设备生命周期状态
const updateLifecycleStatus = (newLifecycle: string) => {
  emit('update-device-lifecycle', props.device, newLifecycle)
}

// 检查租赁是否包含附件
const hasAccessories = (rental: Rental): boolean => {
  return (
    (rental.accessories?.length ?? 0) > 0 ||
    (rental.child_rentals?.length ?? 0) > 0
  )
}

// 清除所有定时器
const clearAllTimers = () => {
  if (showTimer) {
    clearTimeout(showTimer)
    showTimer = null
  }
  if (hideTimer) {
    clearTimeout(hideTimer)
    hideTimer = null
  }
}

// Tooltip事件处理
const handleRentalHover = (rental: Rental, event: MouseEvent) => {
  // 清除所有定时器
  clearAllTimers()
  
  hoveredRental.value = rental
  tooltipTriggerRef.value = event.currentTarget as HTMLElement
  
  // 如果已经显示了，直接更新内容，不需要延迟
  if (tooltipVisible.value) {
    return
  }
  
  // 延迟显示tooltip，避免快速滑过时频繁显示
  showTimer = setTimeout(() => {
    tooltipVisible.value = true
    showTimer = null
  }, 300)
}

const handleRentalLeave = () => {
  // 清除显示定时器
  if (showTimer) {
    clearTimeout(showTimer)
    showTimer = null
  }
  
  // 设置隐藏定时器，给用户时间移动到tooltip上
  hideTimer = setTimeout(() => {
    tooltipVisible.value = false
    hoveredRental.value = null
    hideTimer = null
  }, 500)
}

// Tooltip内部悬停事件处理
const handleTooltipEnter = () => {
  // 当鼠标移到tooltip上时，清除隐藏定时器
  clearAllTimers()
}

const handleTooltipLeave = () => {
  // 当鼠标离开tooltip时，立即隐藏
  clearAllTimers()
  tooltipVisible.value = false
  hoveredRental.value = null
}

// 显示冲突详情
const showConflictDetails = (rental: Rental) => {
  // 清除所有定时器
  clearAllTimers()

  // 设置当前租赁信息
  hoveredRental.value = rental
  tooltipVisible.value = true
}

// 组件卸载时清理定时器和缓存
onUnmounted(() => {
  clearAllTimers()
  rentalDateCache.clear()
})

// 计算属性
// 冲突检测 - 检测相邻租赁之间的档期冲突
const rentalConflicts = computed(() => {
  const conflicts = new Map<number, ConflictInfo>()

  // 过滤掉已取消的租赁并按开始日期排序
  const sortedRentals = [...props.rentals]
    .filter(r => r.status !== 'cancelled')
    .sort((a, b) => dayjs(a.start_date).diff(dayjs(b.start_date)))

  // 检查每对相邻租赁
  for (let i = 0; i < sortedRentals.length - 1; i++) {
    const current = sortedRentals[i]
    const next = sortedRentals[i + 1]

    // 计算时间间隔（天数）
    const endDate = dayjs(current.end_date)
    const nextStartDate = dayjs(next.start_date)
    const hourGap = nextStartDate.diff(endDate, 'hour')

    // 检查位置要求：至少有一方不在广东
    const currentHasGuangdong = current.destination?.includes('广东') ?? false
    const nextHasGuangdong = next.destination?.includes('广东') ?? false
    const locationConflict = !currentHasGuangdong || !nextHasGuangdong

    // 如果时间间隔 ≤ 4天 且位置要求满足，标记为冲突
    if ((hourGap <= 5*24 && locationConflict) || (hourGap <= 3*24)) {
      conflicts.set(current.id, {
        hasConflict: true,
        nextRentalId: next.id,
        dayGap: hourGap/24-1,
        currentDestination: current.destination,
        nextDestination: next.destination
      })
    }
  }

  return conflicts
})

// 当前悬停租赁的冲突信息
const currentRentalConflictInfo = computed(() => {
  if (!hoveredRental.value) return undefined
  return rentalConflicts.value.get(hoveredRental.value.id)
})

// 缓存租赁数据计算结果
const rentalDateCache = new Map<string, Rental[]>()

// 获取有效的条条开始时间（ship_out_time 优先，无则用 start_date）
const getBarStart = (rental: Rental): string => {
  return rental.ship_out_time ? toDateString(rental.ship_out_time) : rental.start_date
}
// 获取有效的条条结束时间（ship_in_time 优先，无则用 end_date）
const getBarEnd = (rental: Rental): string => {
  return rental.ship_in_time ? toDateString(rental.ship_in_time) : rental.end_date
}

const getRentalsForDate = (date: Date) => {
  const dateStr = dayjs(date).format('YYYY-MM-DD')
  // 包含 ship_out_time / ship_in_time，确保这两个字段变化时缓存失效
  const statusHash = props.rentals.map(r => `${r.id}:${r.status}:${r.start_date}:${r.end_date}:${r.ship_out_time}:${r.ship_in_time}`).join('|')
  const cacheKey = `${dateStr}_${props.rentals.length}_${statusHash}`

  if (rentalDateCache.has(cacheKey)) {
    return rentalDateCache.get(cacheKey)!
  }

  const result = props.rentals.filter(rental => {
    const barStart = parseDate(getBarStart(rental))
    const barEnd = parseDate(getBarEnd(rental))
    const currentDate = parseDate(dateStr)

    return (currentDate.isAfter(barStart) || currentDate.isSame(barStart, 'day')) &&
           (currentDate.isBefore(barEnd) || currentDate.isSame(barEnd, 'day'))
  })

  // 限制缓存大小
  if (rentalDateCache.size > 50) {
    const firstKey = rentalDateCache.keys().next().value
    if (firstKey) {
      rentalDateCache.delete(firstKey)
    }
  }

  rentalDateCache.set(cacheKey, result)
  return result
}

const STATUS_COLORS: Record<string, string> = {
  not_shipped:              '#c8860a', // 棕黄色 — 待发货
  scheduled_for_shipping:   '#1989fa', // 蓝色   — 已预约
  shipped:                  '#07c160', // 绿色   — 已发货
  returned:                 '#7232dd', // 紫色   — 已还租
  completed:                '#909399', // 灰色   — 已完成
  cancelled:                '#c8c9cc', // 浅灰   — 已取消
}
const getStatusColor = (status: string): string => STATUS_COLORS[status] ?? '#909399'

const hexToRgba = (hex: string, alpha: number): string => {
  const r = parseInt(hex.slice(1, 3), 16)
  const g = parseInt(hex.slice(3, 5), 16)
  const b = parseInt(hex.slice(5, 7), 16)
  return `rgba(${r}, ${g}, ${b}, ${alpha})`
}

/** 外层条：跨越 ship_out_time → ship_in_time，半透明背景 */
const getShipRangeStyle = (rental: Rental, date: Date) => {
  const barStart = parseDate(getBarStart(rental))
  const barEnd = parseDate(getBarEnd(rental))
  const currentDate = parseDate(toDateString(date))
  const firstVisibleDate = props.dates.length > 0 ? parseDate(toDateString(props.dates[0])) : currentDate

  const isBarStart = currentDate.isSame(barStart, 'day')
  const isFirstVisible = currentDate.isSame(firstVisibleDate, 'day') && barStart.isBefore(firstVisibleDate)

  if (!isBarStart && !isFirstVisible) {
    return {}
  }

  const daysToEnd = barEnd.diff(currentDate, 'day') + 1
  const color = getStatusColor(rental.status)

  return {
    width: `${daysToEnd * 100}%`,
    background: hexToRgba(color, 0.22),
    border: `1px solid ${hexToRgba(color, 0.4)}`,
  }
}

/** 内层条：跨越 start_date → end_date，不透明，绝对定位在外层条内 */
const getRentalPeriodStyle = (rental: Rental, date: Date) => {
  const barStart = parseDate(getBarStart(rental))
  const barEnd = parseDate(getBarEnd(rental))
  const currentDate = parseDate(toDateString(date))
  const firstVisibleDate = props.dates.length > 0 ? parseDate(toDateString(props.dates[0])) : currentDate

  // 外层条实际开始渲染的日期（被可见范围裁剪后）
  const effectiveBarStart = barStart.isBefore(firstVisibleDate) ? firstVisibleDate : barStart

  const startDate = parseDate(rental.start_date)
  const endDate = parseDate(rental.end_date)

  // 内层条裁剪到外层条范围内
  const innerStart = startDate.isBefore(effectiveBarStart) ? effectiveBarStart : startDate
  const innerEnd = endDate.isAfter(barEnd) ? barEnd : endDate

  const totalOuterDays = barEnd.diff(effectiveBarStart, 'day') + 1
  const leftPercent = innerStart.diff(effectiveBarStart, 'day') / totalOuterDays * 100
  const widthPercent = (innerEnd.diff(innerStart, 'day') + 1) / totalOuterDays * 100

  if (widthPercent <= 0) {
    return { display: 'none' }
  }

  const color = getStatusColor(rental.status)

  return {
    position: 'absolute' as const,
    top: '0',
    bottom: '0',
    left: `${leftPercent}%`,
    width: `${widthPercent}%`,
    background: color,
    borderRadius: '4px',
    display: 'flex',
    alignItems: 'center',
    padding: '0 8px',
    color: 'white',
    fontSize: '12px',
  }
}

// Check if this date is the first day of rental
const isRentalFirstDay = (rental: Rental, date: Date) => {
  const startDate = parseDate(rental.start_date)
  const currentDate = parseDate(toDateString(date))
  return currentDate.isSame(startDate, 'day')
}

// Check if this is the first visible day for the rental (either actual bar start or first visible date)
const isRentalFirstVisibleDay = (rental: Rental, date: Date) => {
  const barStart = parseDate(getBarStart(rental))
  const currentDate = parseDate(toDateString(date))
  const firstVisibleDate = props.dates.length > 0 ? parseDate(toDateString(props.dates[0])) : currentDate

  // 如果是实际开始日期（ship_out_time 或 start_date）
  if (currentDate.isSame(barStart, 'day')) {
    return true
  }

  // 如果开始日期在可见范围之前，且当前是可见范围的第一天
  if (barStart.isBefore(firstVisibleDate) && currentDate.isSame(firstVisibleDate, 'day')) {
    return true
  }

  return false
}

// Check if rental bar should be shown on this date (only show on first visible day)
const shouldShowRentalBar = (rental: Rental, date: Date) => {
  return isRentalFirstVisibleDay(rental, date)
}

// Calculate rental duration in days
const getRentalDuration = (rental: Rental) => {
  const startDate = parseDate(rental.start_date)
  const endDate = parseDate(rental.end_date)
  return endDate.diff(startDate, 'day') + 1
}

// Format rental date range for display
const formatRentalDateRange = (rental: Rental) => {
  const start = dayjs(rental.start_date)
  const end = dayjs(rental.end_date)
  return `${start.format('M/D')}-${end.format('M/D')}`
}

// Check if date has no rentals for this device
const isDateEmpty = (date: Date) => {
  const rentalsForDate = getRentalsForDate(date)
  return rentalsForDate.length === 0
}

</script>

<style scoped>
.gantt-row {
  display: flex;
  border-bottom: 2px solid #e0e0e0;
  min-height: 44px;
  position: relative;
  width: 100%;
  min-width: max-content;
}

.device-cell {
  min-width: 200px;
  width: 200px;
  padding: 6px 12px;
  border-right: 2px solid #d0d0d0;
  background: #f5f5f5;
  position: sticky;
  left: 0;
  z-index: 5;
  flex-shrink: 0;
  height: 100%;
}

.device-cell.device-status-online {
  background-color: #f6ffed;
  border-left: 4px solid #52c41a;
}

.device-cell.device-status-offline {
  background-color: #fff1f0;
  border-left: 4px solid #ff4d4f;
}

.device-cell.device-status-returned {
  background-color: #f4f4f5;
  border-left: 4px solid #8c8c8c;
}

.device-cell.device-status-offline {
  background-color: #fff2f0;
  border-left: 4px solid #ff4d4f;
}

.device-info {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.device-name {
  font-weight: 600;
  font-size: 14px;
  color: var(--el-text-color-primary);
}

.device-details {
  display: flex;
  align-items: center;
  gap: 8px;
}

.device-lifecycle {
  margin-top: 4px;
}

.device-cell.device-lifecycle-sold {
  opacity: 0.55;
  border-left: 4px solid #fa8c16 !important;
}

.device-cell.device-lifecycle-damaged {
  opacity: 0.55;
  border-left: 4px solid #eb2f96 !important;
}

.device-cell.device-lifecycle-decommissioned,
.device-cell.device-lifecycle-retired {
  opacity: 0.45;
  border-left: 4px solid #8c8c8c !important;
}

.device-sn {
  font-size: 12px;
  color: var(--el-text-color-regular);
}

.device-location {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.date-cell {
  min-width: 80px;
  width: 80px;
  border-right: 1px solid #d0d0d0;
  position: relative;
  padding: 4px 2px;
  background: white;
}

.date-cell.is-today {
  background: var(--el-color-primary-light-9);
}

.date-cell.is-weekend {
  background: #fffbf0;
}

.date-cell.is-today.is-weekend {
  background: linear-gradient(135deg, var(--el-color-primary-light-9) 50%, #fffbf0 50%);
}

.date-cell.is-empty {
  background-image:
    linear-gradient(45deg, #f9f9f9 25%, transparent 25%),
    linear-gradient(-45deg, #f9f9f9 25%, transparent 25%),
    linear-gradient(45deg, transparent 75%, #f9f9f9 75%),
    linear-gradient(-45deg, transparent 75%, #f9f9f9 75%);
  background-size: 8px 8px;
  background-position: 0 0, 0 4px, 4px -4px, -4px 0px;
}

.date-cell.is-empty.is-today {
  background-color: var(--el-color-primary-light-9);
  background-image:
    linear-gradient(45deg, rgba(249, 249, 249, 0.6) 25%, transparent 25%),
    linear-gradient(-45deg, rgba(249, 249, 249, 0.6) 25%, transparent 25%),
    linear-gradient(45deg, transparent 75%, rgba(249, 249, 249, 0.6) 75%),
    linear-gradient(-45deg, transparent 75%, rgba(249, 249, 249, 0.6) 75%);
  background-size: 8px 8px;
  background-position: 0 0, 0 4px, 4px -4px, -4px 0px;
}

.date-cell.is-empty.is-weekend {
  background-color: #fffbf0;
  background-image:
    linear-gradient(45deg, rgba(249, 249, 249, 0.6) 25%, transparent 25%),
    linear-gradient(-45deg, rgba(249, 249, 249, 0.6) 25%, transparent 25%),
    linear-gradient(45deg, transparent 75%, rgba(249, 249, 249, 0.6) 75%),
    linear-gradient(-45deg, transparent 75%, rgba(249, 249, 249, 0.6) 75%);
  background-size: 8px 8px;
  background-position: 0 0, 0 4px, 4px -4px, -4px 0px;
}

.rental-bar {
  position: absolute;
  top: 8px;
  left: 2px;
  right: 2px;
  height: 44px;
  border-radius: 4px;
  cursor: pointer;
  transition: all 0.2s;
  position: relative;
  z-index: 2;
  overflow: visible;
}

.rental-period {
  position: absolute;
  top: 0;
  bottom: 0;
  border-radius: 4px;
  display: flex;
  align-items: center;
  padding: 0 8px;
  color: white;
  font-size: 12px;
  overflow: visible;
  min-width: 20px;
}

.rental-bar:hover {
  transform: translateY(-1px);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
  z-index: 10;
}

/* 档期冲突警告图标 */
.conflict-warning-icon {
  position: absolute;
  top: 2px;
  right: 2px;
  font-size: 16px;
  cursor: pointer;
  z-index: 10;
  filter: drop-shadow(0 0 2px rgba(255, 193, 7, 0.6));
  transition: transform 0.2s;
  line-height: 1;
}

.conflict-warning-icon:hover {
  transform: scale(1.2);
  filter: drop-shadow(0 0 4px rgba(255, 193, 7, 0.9));
}

.rental-content {
  display: flex;
  flex-direction: column;
  gap: 2px;
  width: 100%;
  min-width: 100px;
  overflow: visible;
  position: relative;
  z-index: 1;
}

.rental-customer-line {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 4px;
  width: 100%;
}

.rental-customer {
  font-weight: 600;
  white-space: nowrap;
  overflow: visible;
  flex: 1;
  min-width: 0;
  text-shadow:
    1px  1px 0 rgba(0,0,0,0.5),
    -1px -1px 0 rgba(0,0,0,0.5),
    1px -1px 0 rgba(0,0,0,0.5),
    -1px  1px 0 rgba(0,0,0,0.5);
}

.accessory-icon {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.9);
  flex-shrink: 0;
  background: rgba(255, 255, 255, 0.2);
  border-radius: 50%;
  width: 16px;
  height: 16px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.rental-phone {
  font-size: 10px;
  opacity: 0.9;
  white-space: nowrap;
  overflow: visible;
  text-shadow:
    1px  1px 0 rgba(0,0,0,0.5),
    -1px -1px 0 rgba(0,0,0,0.5),
    1px -1px 0 rgba(0,0,0,0.5),
    -1px  1px 0 rgba(0,0,0,0.5);
}

.status-icon {
  margin-right: 4px;
  font-size: 12px;
}

.shipped-icon {
  color: #52c41a;
  filter: drop-shadow(0 0 2px rgba(82, 196, 26, 0.3));
}

.returned-icon {
  color: #52c41a;
  filter: drop-shadow(0 0 2px rgba(82, 196, 26, 0.3));
}
</style>
