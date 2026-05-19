<template>
  <div class="gantt-row">
    <div class="device-cell" :class="[`device-status-${device.status}`, `device-lifecycle-${device.lifecycle_status || 'active'}`]">
      <div class="device-info">
        <div class="device-name">{{ device.name }}</div>
        <div class="device-details">
          <span class="device-sn">{{ device.serial_number }}</span>
          <el-select
            :model-value="device.status"
            size="small"
            style="width: 80px;"
            @change="updateDeviceStatus"
          >
            <el-option label="在线" value="online" />
            <el-option label="离线" value="offline" />
          </el-select>
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
      <!-- Consolidated rental bar with shipping overlay -->
      <div
        v-for="rental in getRentalsForDate(date)"
        :key="`rental-${rental.id}`"
        v-show="shouldShowRentalBar(rental, date)"
        class="rental-bar rental-period"
        :style="getRentalStyle(rental, date)"
        @click="$emit('edit-rental', rental)"
        @dblclick="$emit('delete-rental', rental)"
        @mouseenter="handleRentalHover(rental, $event)"
        @mouseleave="handleRentalLeave"
      >
        <!-- Shipping period overlay (transparent background layer) -->
        <div
          v-if="rental.ship_out_time && rental.ship_in_time"
          class="rental-ship-overlay"
          :style="getRentalShipOverlayStyle(rental, date)"
        />
        
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
import { ref, computed, defineAsyncComponent, onUnmounted, type CSSProperties } from 'vue'
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

const getRentalsForDate = (date: Date) => {
  const dateStr = dayjs(date).format('YYYY-MM-DD')
  // 添加status和日期到缓存key中，确保状态或日期变化时缓存失效
  const statusHash = props.rentals.map(r => `${r.id}:${r.status}:${r.start_date}:${r.end_date}`).join('|')
  const cacheKey = `${dateStr}_${props.rentals.length}_${statusHash}`

  if (rentalDateCache.has(cacheKey)) {
    return rentalDateCache.get(cacheKey)!
  }

  const result = props.rentals.filter(rental => {
    const startDate = parseDate(rental.start_date)
    const endDate = parseDate(rental.end_date)
    const currentDate = parseDate(dateStr)

    return (currentDate.isAfter(startDate) || currentDate.isSame(startDate, 'day')) &&
           (currentDate.isBefore(endDate) || currentDate.isSame(endDate, 'day'))
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

const getRentalStyle = (rental: Rental, date: Date) => {
  const startDate = parseDate(rental.start_date)
  const endDate = parseDate(rental.end_date)
  const currentDate = parseDate(toDateString(date))

  // 找到可见范围内的第一天
  const firstVisibleDate = props.dates.length > 0 ? parseDate(toDateString(props.dates[0])) : currentDate

  // 计算在当前日期格子中的显示样式
  let width = '100%'
  let marginLeft = '0%'

  // 如果是租赁的第一天，或者是可见范围内的第一天（当rental开始日期在可见范围之前）
  const isRentalStart = currentDate.isSame(startDate, 'day')
  const isFirstVisible = currentDate.isSame(firstVisibleDate, 'day') && startDate.isBefore(firstVisibleDate)

  if (isRentalStart || isFirstVisible) {
    // 计算从当前日期到结束日期的天数
    const daysToEnd = endDate.diff(currentDate, 'day') + 1
    width = `${daysToEnd * 100}%`
  }

  const bgColor = getRentalColor(rental.status)
  return {
    width,
    marginLeft,
    background: `
      repeating-linear-gradient(
        to right,
        transparent,
        transparent 79px,
        rgba(255, 255, 255, 0.6) 79px,
        rgba(255, 255, 255, 0.6) 80px
      ),
      ${bgColor}
    `,
    backgroundPosition: '-2px 0',
    opacity: getRentalOpacity(rental)
  }
}

// NEW: 计算物流期间的叠加样式
const getRentalShipOverlayStyle = (rental: Rental, date: Date): CSSProperties => {
  if (!rental.ship_out_time || !rental.ship_in_time) {
    return {}
  }

  // 简单的日期字符串处理
  const shipOutDateStr = toDateString(rental.ship_out_time)
  const shipInDateStr = toDateString(rental.ship_in_time)
  const currentDateStr = toDateString(date)

  const shipOutDate = parseDate(shipOutDateStr)
  const shipInDate = parseDate(shipInDateStr)
  const currentDate = parseDate(currentDateStr)
  const firstVisibleDate = props.dates.length > 0 ? parseDate(toDateString(props.dates[0])) : currentDate

  // 计算在当前日期格子中的显示样式
  let width = '100%'
  let marginLeft = '0%'

  // 如果是物流的第一天，或者是可见范围内的第一天（当ship开始日期在可见范围之前）
  const isShipStart = currentDateStr === shipOutDateStr
  const isFirstVisible = currentDate.isSame(firstVisibleDate, 'day') && shipOutDate.isBefore(firstVisibleDate)

  if (isShipStart || isFirstVisible) {
    // 计算从当前日期到结束日期的天数
    const daysToEnd = shipInDate.diff(currentDate, 'day') + 1
    width = `${daysToEnd * 100}%`
  }

  const bgColor = generateRandomColor(rental.id)
  return {
    position: 'absolute',
    top: 0,
    left: marginLeft,
    width,
    height: '100%',
    background: `
      repeating-linear-gradient(
        to right,
        transparent,
        transparent 79px,
        rgba(255, 255, 255, 0.4) 79px,
        rgba(255, 255, 255, 0.4) 80px
      ),
      ${bgColor}
    `,
    backgroundPosition: '-2px 0',
    opacity: '0.4',
    borderRadius: '4px',
    zIndex: 0,
    pointerEvents: 'none' as const
  } as CSSProperties
}

// 生成随机颜色的函数
const generateRandomColor = (rentalId: number) => {
  // 使用rentalId作为种子，确保同一个rental总是得到相同的颜色
  const colors = [
    '#FF6B6B', '#4ECDC4', '#45B7D1', '#96CEB4', '#FFEAA7',
    '#DDA0DD', '#98D8C8', '#F7DC6F', '#BB8FCE', '#85C1E9',
    '#F8C471', '#82E0AA', '#F1948A', '#85C1E9', '#D7BDE2',
    '#F9E79F', '#D5A6BD', '#A9CCE3', '#FAD7A0', '#D2B4DE',
    '#FF8A80', '#80CBC4', '#81C784', '#FFB74D', '#BA68C8',
    '#64B5F6', '#A1887F', '#90A4AE', '#FFAB91', '#C5E1A5',
    '#BCAAA4', '#B39DDB', '#F48FB1', '#80DEEA', '#DCEDC8',
    '#FFE082', '#FFCDD2', '#D1C4E9', '#C8E6C9', '#FFF3E0',
    '#FF7043', '#26A69A', '#AB47BC', '#5C6BC0', '#EF5350',
    '#66BB6A', '#FFA726', '#EC407A', '#42A5F5', '#FFCA28',
    '#26C6DA', '#7E57C2', '#FF5722', '#009688', '#795548',
    '#607D8B', '#FFC107', '#9C27B0', '#3F51B5', '#F44336',
    '#4CAF50', '#FF9800', '#E91E63', '#2196F3', '#CDDC39',
    '#00BCD4', '#673AB7', '#FF6F00', '#E65100', '#BF360C',
    '#1B5E20', '#0D47A1', '#4A148C', '#B71C1C', '#33691E'
  ]
  return colors[rentalId % colors.length]
}

const getRentalColor = (status: string) => {
  const colorMap: Record<string, string> = {
    'not_shipped': '#e6a23c',  // 未发货 - 橙色
    'shipped': '#67c23a',      // 已发货 - 绿色
    'returned': '#409eff',     // 已收回 - 蓝色
    'completed': '#909399',    // 已完成 - 灰色
    'cancelled': '#f56c6c',    // 已取消 - 红色
    'default': '#409eff'       // 默认 - 蓝色
  }
  return colorMap[status] || colorMap.default
}

const getRentalOpacity = (rental: Rental) => {
  // 根据寄出时间和收回时间调整透明度
  if (rental.ship_out_time && rental.ship_in_time) {
    return '0.9'
  } else if (rental.ship_out_time) {
    return '0.7'
  }
  return '0.5'
}

// Check if this date is the first day of rental
const isRentalFirstDay = (rental: Rental, date: Date) => {
  const startDate = parseDate(rental.start_date)
  const currentDate = parseDate(toDateString(date))
  return currentDate.isSame(startDate, 'day')
}

// Check if this is the first visible day for the rental (either actual start or first visible date)
const isRentalFirstVisibleDay = (rental: Rental, date: Date) => {
  const startDate = parseDate(rental.start_date)
  const currentDate = parseDate(toDateString(date))
  const firstVisibleDate = props.dates.length > 0 ? parseDate(toDateString(props.dates[0])) : currentDate

  // 如果是实际开始日期
  if (currentDate.isSame(startDate, 'day')) {
    return true
  }

  // 如果开始日期在可见范围之前，且当前是可见范围的第一天
  if (startDate.isBefore(firstVisibleDate) && currentDate.isSame(firstVisibleDate, 'day')) {
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
  min-height: 60px;
  position: relative;
  width: 100%;
  min-width: max-content;
}

.device-cell {
  min-width: 200px;
  width: 200px;
  padding: 12px 16px;
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
  min-width: 120px;
  border-radius: 4px;
  cursor: pointer;
  transition: all 0.2s;
  display: flex;
  align-items: center;
  padding: 0 8px;
  color: white;
  font-size: 12px;
  border: 1px solid rgba(255, 255, 255, 0.3);
  position: relative;
  z-index: 2;
}

.rental-bar:hover {
  transform: translateY(-1px);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
  z-index: 10;
}

/* Shipping overlay - positioned absolutely within rental bar */
.rental-ship-overlay {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  border-radius: 4px;
  z-index: 0;
  opacity: 0.4;
  pointer-events: none;
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
  overflow: hidden;
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
  overflow: hidden;
  text-overflow: ellipsis;
  flex: 1;
  min-width: 0;
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
  overflow: hidden;
  text-overflow: ellipsis;
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
