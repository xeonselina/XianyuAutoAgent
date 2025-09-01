<template>
  <div class="gantt-row">
    <div class="device-cell" :class="`device-status-${device.status}`">
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
            <el-option label="空闲" value="idle" />
            <el-option label="待寄出" value="pending_ship" />
            <el-option label="租赁中" value="renting" />
            <el-option label="待收回" value="pending_return" />
            <el-option label="已归还" value="returned" />
            <el-option label="离线" value="offline" />
          </el-select>
        </div>
      </div>
    </div>

    <div 
      v-for="date in dates" 
      :key="date.toString()"
      class="date-cell"
      :class="{ 'is-today': isToday(date) }"
    >
      <!-- 原有的rental时间段标记（棕色） -->
      <div 
        v-for="rental in getRentalsForDate(date)"
        :key="`rental-${rental.id}`"
        class="rental-bar rental-period"
        :style="getRentalStyle(rental, date)"
        @click="$emit('edit-rental', rental)"
        @dblclick="$emit('delete-rental', rental)"
        @mouseenter="handleRentalHover(rental, $event)"
        @mouseleave="handleRentalLeave"
      >
        <div class="rental-content">
          <span class="rental-customer">{{ rental.customer_name }}</span>
          <span class="rental-phone">{{ rental.customer_phone }}</span>
        </div>
      </div>
      
      <!-- 新的ship_out_time到ship_in_time时间段标记（随机颜色） -->
      <div 
        v-for="rental in getShipTimeRentalsForDate(date)"
        :key="`ship-${rental.id}`"
        class="rental-bar ship-time-period"
        :style="getShipTimeStyle(rental, date)"
        @click="$emit('edit-rental', rental)"
        @dblclick="$emit('delete-rental', rental)"
        @mouseenter="handleRentalHover(rental, $event)"
        @mouseleave="handleRentalLeave"
      >
        <div class="rental-content">
          <span class="rental-customer">🚚 物流</span>
          <span class="rental-phone">{{ rental.customer_name }}</span>
        </div>
      </div>
    </div>
    
    <!-- Tooltip组件 -->
    <RentalTooltip 
      :rental="hoveredRental"
      :visible="tooltipVisible"
      :trigger-ref="tooltipTriggerRef"
      @tooltip-enter="handleTooltipEnter"
      @tooltip-leave="handleTooltipLeave"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, ref, defineAsyncComponent, onUnmounted } from 'vue'
import type { Device, Rental } from '../stores/gantt'
import {
  toSystemDateString,
  isSameDay,
  parseSystemDate,
  isToday
} from '@/utils/dateUtils'
import dayjs from 'dayjs'

const RentalTooltip = defineAsyncComponent(() => import('./RentalTooltip.vue'))

interface Props {
  device: Device
  rentals: Rental[]
  dates: Date[]
}

const props = defineProps<Props>()

const emit = defineEmits<{
  'edit-rental': [rental: Rental]
  'delete-rental': [rental: Rental]
  'update-device-status': [device: Device, newStatus: string]
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

// 组件卸载时清理定时器
onUnmounted(() => {
  clearAllTimers()
})

// 计算属性

const getRentalsForDate = (date: Date) => {
  const dateStr = dayjs(date).format('YYYY-MM-DD')
  return props.rentals.filter(rental => {
    const startDate = parseSystemDate(rental.start_date)
    const endDate = parseSystemDate(rental.end_date)
    const currentDate = parseSystemDate(dateStr)
    
    return (currentDate.isAfter(startDate) || currentDate.isSame(startDate, 'day')) && 
           (currentDate.isBefore(endDate) || currentDate.isSame(endDate, 'day'))
  })
}

const getShipTimeRentalsForDate = (date: Date) => {
  const dateStr = dayjs(date).format('YYYY-MM-DD')
  return props.rentals.filter(rental => {
    // 检查是否有ship_out_time和ship_in_time
    if (!rental.ship_out_time || !rental.ship_in_time) {
      return false
    }
    
    // 使用统一时区处理
    const shipOutDate = toSystemDateString(rental.ship_out_time)
    const shipInDate = toSystemDateString(rental.ship_in_time)
    const currentDate = dateStr
    
    return (currentDate >= shipOutDate) && (currentDate <= shipInDate)
  })
}

const getRentalStyle = (rental: Rental, date: Date) => {
  const startDate = parseSystemDate(rental.start_date)
  const endDate = parseSystemDate(rental.end_date)
  const currentDate = parseSystemDate(toSystemDateString(date))
  
  // 计算在当前日期格子中的显示样式
  let width = '100%'
  let marginLeft = '0%'
  
  // 如果是租赁的第一天
  if (currentDate.isSame(startDate, 'day')) {
    const totalDays = endDate.diff(startDate, 'day') + 1
    const currentDateIndex = props.dates.findIndex(d => isSameDay(d, currentDate.toDate()))
    width = `${Math.min(totalDays * 100, (props.dates.length - currentDateIndex) * 100)}%`
  }
  
  return {
    width,
    marginLeft,
    backgroundColor: getRentalColor(rental.status),
    opacity: getRentalOpacity(rental)
  }
}

const getShipTimeStyle = (rental: Rental, date: Date) => {
  // 使用统一时区处理
  const shipOutDateStr = dayjs(rental.ship_out_time!).format('YYYY-MM-DD')
  const shipInDateStr = dayjs(rental.ship_in_time!).format('YYYY-MM-DD')
  const currentDateStr = toSystemDateString(date)
  
  // 计算在当前日期格子中的显示样式
  let width = '100%'
  let marginLeft = '0%'
  
  // 如果是物流的第一天
  if (currentDateStr === shipOutDateStr) {
    const shipOutDate = parseSystemDate(shipOutDateStr)
    const shipInDate = parseSystemDate(shipInDateStr)
    const totalDays = shipInDate.diff(shipOutDate, 'day') + 1
    const currentDateIndex = props.dates.findIndex(d => toSystemDateString(d) === currentDateStr)
    const remainingDays = props.dates.length - currentDateIndex
    width = `${Math.min(totalDays * 100, remainingDays * 100)}%`
  }
  
  return {
    width,
    marginLeft,
    backgroundColor: generateRandomColor(rental.id),
    opacity: '0.8'
  }
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
    'pending': '#e6a23c',      // 待确认 - 橙色
    'confirmed': '#409eff',    // 已确认 - 蓝色  
    'shipped': '#67c23a',      // 已发货 - 绿色
    'returned': '#909399',     // 已归还 - 灰色
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

const getStatusType = (status: string) => {
  const typeMap: Record<string, string> = {
    'idle': 'success',
    'pending_ship': 'warning',
    'renting': 'primary',
    'pending_return': 'info',
    'returned': 'success',
    'offline': 'danger'
  }
  return typeMap[status] || 'info'
}

const getStatusText = (status: string) => {
  const textMap: Record<string, string> = {
    'idle': '空闲',
    'pending_ship': '待寄出',
    'renting': '租赁中',
    'pending_return': '待收回',
    'returned': '已归还',
    'offline': '离线'
  }
  return textMap[status] || status
}
</script>

<style scoped>
.gantt-row {
  display: flex;
  border-bottom: 1px solid var(--el-border-color-lighter);
  min-height: 60px;
  position: relative;
  width: 100%;
  min-width: max-content;
}

.device-cell {
  min-width: 200px;
  width: 200px;
  padding: 12px 16px;
  border-right: 1px solid var(--el-border-color);
  background: #f5f5f5;
  position: sticky;
  left: 0;
  z-index: 5;
  flex-shrink: 0;
  height: 100%;
}

.device-cell.device-status-idle {
  background-color: #f6ffed;
  border-left: 4px solid #52c41a;
}

.device-cell.device-status-pending_ship {
  background-color: #fff2f0;
  border-left: 4px solid #ff4d4f;
}

.device-cell.device-status-renting {
  background-color: #e6f7ff;
  border-left: 4px solid #1890ff;
}

.device-cell.device-status-pending_return {
  background-color: #fffbe6;
  border-left: 4px solid #faad14;
}

.device-cell.device-status-returned {
  background-color: #fff7e6;
  border-left: 4px solid #d46b08;
}

.device-cell.device-status-offline {
  background-color: #fafafa;
  border-left: 4px solid #8c8c8c;
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
  border-right: 1px solid var(--el-border-color-lighter);
  position: relative;
  padding: 4px 2px;
  background: white;
}

.date-cell.is-today {
  background: var(--el-color-primary-light-9);
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
  display: flex;
  align-items: center;
  padding: 0 8px;
  color: white;
  font-size: 12px;
  border: 1px solid rgba(255, 255, 255, 0.3);
}

/* 租赁时间段标记 */
.rental-period {
  top: 8px;
  z-index: 2;
}

/* 物流时间段标记 */
.ship-time-period {
  top: 24px;
  height: 35px;
  z-index: 1;
  opacity: 0.8;
}

.rental-bar:hover {
  transform: translateY(-1px);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
  z-index: 10;
}

.rental-content {
  display: flex;
  flex-direction: column;
  gap: 2px;
  width: 100%;
  overflow: hidden;
}

.rental-customer {
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.rental-phone {
  font-size: 10px;
  opacity: 0.9;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
</style>
