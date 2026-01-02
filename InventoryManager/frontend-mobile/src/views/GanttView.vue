<template>
  <div class="gantt-view">
    <!-- 顶部导航栏 -->
    <van-nav-bar title="设备档期" fixed>
      <template #right>
        <van-icon name="search" @click="showSearch = true" />
      </template>
    </van-nav-bar>
    
    <!-- 日期导航 -->
    <div class="date-picker">
      <van-button size="small" @click="navigateWeek(-1)">
        <van-icon name="arrow-left" />
        上周
      </van-button>
      <van-button size="small" type="primary" @click="goToToday">
        今天
      </van-button>
      <van-button size="small" @click="navigateWeek(1)">
        下周
        <van-icon name="arrow" />
      </van-button>
      <van-button size="small" @click="showDatePicker = true">
        <van-icon name="calendar-o" />
        跳转
      </van-button>
    </div>

    <!-- 日期选择器弹窗 -->
    <van-popup v-model:show="showDatePicker" position="bottom">
      <van-date-picker
        v-model="selectedDate"
        title="选择日期"
        :min-date="minDate"
        :max-date="maxDate"
        @confirm="onDatePickerConfirm"
        @cancel="showDatePicker = false"
      />
    </van-popup>

    <!-- 日期标题行 (新增) -->
    <MobileDateHeader />

    <!-- 设备列表 -->
    <van-pull-refresh v-model="refreshing" @refresh="onRefresh">
      <div v-if="ganttStore.loading && !refreshing" class="loading-container">
        <van-loading type="spinner" size="24px">加载中...</van-loading>
      </div>
      
      <div v-else-if="ganttStore.filteredDevices.length === 0" class="empty-container">
        <van-empty description="暂无设备数据" />
      </div>
      
      <div v-else class="device-list">
        <div 
          v-for="device in ganttStore.filteredDevices" 
          :key="device.id" 
          class="device-row"
        >
          <van-cell>
            <template #title>
              <div class="device-title">
                <span class="device-name">{{ device.name }}</span>
                <van-tag :type="device.status === 'online' ? 'success' : 'danger'">
                  {{ device.status === 'online' ? '在线' : '离线' }}
                </van-tag>
              </div>
            </template>
            <template #label>
              <div class="device-info">
                <span>{{ device.model }}</span>
                <span v-if="device.serial_number"> · {{ device.serial_number }}</span>
              </div>
              
              <!-- 简化的时间轴 -->
              <div class="timeline-container">
                <div class="timeline">
                  <div 
                    v-for="block in getTimelineBlocks(device)" 
                    :key="block.rental.id"
                    class="rental-block"
                    :style="{
                      left: `${block.left}%`,
                      width: `${block.width}%`,
                      background: block.color
                    }"
                    @click="showRentalDetail(block.rental)"
                  >
                    <span class="rental-label">{{ block.rental.customer_name }}</span>
                  </div>
                  
                  <!-- 今天的标记线 -->
                  <div 
                    class="today-marker"
                    :style="{ left: `${getTodayPosition()}%` }"
                  />
                </div>
              </div>
            </template>
          </van-cell>
        </div>
      </div>
    </van-pull-refresh>
    
    <!-- 搜索弹窗 -->
    <van-popup v-model:show="showSearch" position="top" :style="{ height: '120px' }">
      <van-search
        v-model="searchText"
        placeholder="搜索设备或客户名称"
        show-action
        @search="onSearch"
        @clear="onClearSearch"
      >
        <template #action>
          <div @click="onSearch">搜索</div>
        </template>
      </van-search>
    </van-popup>
    
    <!-- 租赁详情弹窗 -->
    <van-popup v-model:show="showDetail" position="bottom" :style="{ height: '60%' }">
      <div v-if="selectedRental" class="rental-detail">
        <van-nav-bar title="租赁详情" />
        <van-cell-group>
          <van-cell title="客户名称" :value="selectedRental.customer_name" />
          <van-cell title="联系电话" :value="selectedRental.customer_phone || '-'" />
          <van-cell title="目的地" :value="selectedRental.destination || '-'" />
          <van-cell title="开始日期" :value="selectedRental.start_date" />
          <van-cell title="结束日期" :value="selectedRental.end_date" />
          <van-cell title="发出时间" :value="formatDateTime(selectedRental.ship_out_time)" />
          <van-cell title="归还时间" :value="formatDateTime(selectedRental.ship_in_time)" />
          <van-cell title="状态">
            <template #value>
              <van-tag :type="getRentalStatusType(selectedRental.status)">
                {{ getRentalStatusText(selectedRental.status) }}
              </van-tag>
            </template>
          </van-cell>
          <van-cell 
            v-if="selectedRental.xianyu_order_no" 
            title="闲鱼订单号" 
            :value="selectedRental.xianyu_order_no" 
          />
          <van-cell 
            v-if="selectedRental.order_amount" 
            title="订单金额" 
            :value="`¥${selectedRental.order_amount}`" 
          />
        </van-cell-group>
      </div>
    </van-popup>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useGanttStore } from '@/stores/gantt'
import dayjs from 'dayjs'
import type { Rental, GanttDevice, TimelineBlock, RentalStatus } from '@/types'
import { showToast } from 'vant'
import MobileDateHeader from '@/components/MobileDateHeader.vue'

const ganttStore = useGanttStore()

// State
const refreshing = ref(false)
const showSearch = ref(false)
const showDetail = ref(false)
const showDatePicker = ref(false)
const searchText = ref('')
const selectedRental = ref<Rental | null>(null)
const selectedDate = ref<string[]>([
  dayjs().format('YYYY'),
  dayjs().format('MM'),
  dayjs().format('DD')
])
const minDate = ref(new Date(2020, 0, 1))
const maxDate = ref(new Date(2030, 11, 31))

// 生命周期
onMounted(() => {
  ganttStore.loadGanttData()
})

/**
 * 下拉刷新
 */
const onRefresh = async () => {
  try {
    await ganttStore.refreshData()
    showToast({
      message: '刷新成功',
      position: 'top'
    })
  } catch (err) {
    showToast({
      message: '刷新失败',
      position: 'top'
    })
  } finally {
    refreshing.value = false
  }
}

/**
 * 导航到上一周/下一周
 */
const navigateWeek = (direction: number) => {
  if (direction < 0) {
    ganttStore.navigatePreviousWeek()
  } else {
    ganttStore.navigateNextWeek()
  }
}

/**
 * 前往今天
 */
const goToToday = () => {
  ganttStore.goToToday()
}

/**
 * 日期选择器确认
 */
const onDatePickerConfirm = ({ selectedValues }: { selectedValues: string[] }) => {
  const dateStr = `${selectedValues[0]}-${selectedValues[1]}-${selectedValues[2]}`
  ganttStore.jumpToDate(dateStr)
  showDatePicker.value = false
}

/**
 * 搜索
 */
const onSearch = () => {
  ganttStore.setSearchKeyword(searchText.value)
  showSearch.value = false
}

/**
 * 清空搜索
 */
const onClearSearch = () => {
  searchText.value = ''
  ganttStore.clearSearch()
}

/**
 * 显示租赁详情
 */
const showRentalDetail = (rental: Rental) => {
  selectedRental.value = rental
  showDetail.value = true
}

/**
 * 格式化日期范围
 */
const formatDateRange = (start: string, end: string) => {
  return `${dayjs(start).format('M月D日')} - ${dayjs(end).format('M月D日')}`
}

/**
 * 格式化日期时间
 */
const formatDateTime = (datetime: string | null) => {
  if (!datetime) return '-'
  return dayjs(datetime).format('YYYY-MM-DD HH:mm')
}

/**
 * 获取租赁状态文本
 */
const getRentalStatusText = (status: RentalStatus) => {
  const statusMap: Record<RentalStatus, string> = {
    not_shipped: '未发货',
    scheduled_for_shipping: '待发货',
    shipped: '已发货',
    returned: '已归还',
    completed: '已完成',
    cancelled: '已取消'
  }
  return statusMap[status] || status
}

/**
 * 获取租赁状态类型(用于Tag组件)
 */
const getRentalStatusType = (status: RentalStatus): 'default' | 'primary' | 'success' | 'danger' | 'warning' => {
  const typeMap: Record<RentalStatus, 'default' | 'primary' | 'success' | 'danger' | 'warning'> = {
    not_shipped: 'default',
    scheduled_for_shipping: 'warning',
    shipped: 'primary',
    returned: 'success',
    completed: 'success',
    cancelled: 'danger'
  }
  return typeMap[status] || 'default'
}

/**
 * 计算今天在时间轴上的位置 (百分比)
 */
const getTodayPosition = () => {
  const start = dayjs(ganttStore.currentStartDate)
  const end = dayjs(ganttStore.currentEndDate)
  const today = dayjs()
  
  if (today.isBefore(start) || today.isAfter(end)) {
    return -10 // 不在可视范围内
  }
  
  const totalDays = end.diff(start, 'day')
  const daysFromStart = today.diff(start, 'day')
  
  return (daysFromStart / totalDays) * 100
}

/**
 * 计算设备的时间轴块
 */
const getTimelineBlocks = (device: GanttDevice): TimelineBlock[] => {
  const start = dayjs(ganttStore.currentStartDate)
  const end = dayjs(ganttStore.currentEndDate)
  const totalDays = end.diff(start, 'day')
  
  if (totalDays === 0) return []
  
  const blocks: TimelineBlock[] = []
  
  // 只显示在当前日期范围内的租赁
  const visibleRentals = device.rentals.filter(rental => {
    const rentalStart = dayjs(rental.start_date)
    const rentalEnd = dayjs(rental.end_date)
    
    // 租赁期与可视范围有交集
    return rentalEnd.isAfter(start) && rentalStart.isBefore(end)
  })
  
  visibleRentals.forEach(rental => {
    const rentalStart = dayjs(rental.start_date)
    const rentalEnd = dayjs(rental.end_date)
    
    // 计算租赁块的起始位置(相对于可视范围)
    const blockStart = rentalStart.isBefore(start) ? start : rentalStart
    const blockEnd = rentalEnd.isAfter(end) ? end : rentalEnd
    
    const daysFromStart = blockStart.diff(start, 'day')
    const blockDuration = blockEnd.diff(blockStart, 'day') + 1
    
    const left = (daysFromStart / totalDays) * 100
    const width = (blockDuration / totalDays) * 100
    
    // 根据状态设置颜色
    let color = '#1989fa' // 默认蓝色
    if (rental.status === 'completed') {
      color = '#07c160' // 绿色
    } else if (rental.status === 'cancelled') {
      color = '#ee0a24' // 红色
    } else if (rental.status === 'shipped') {
      color = '#ff976a' // 橙色
    }
    
    blocks.push({
      rental,
      left,
      width,
      color
    })
  })
  
  return blocks
}
</script>

<style scoped>
.gantt-view {
  padding-bottom: 50px; /* 留出底部导航栏空间 */
  background: #f7f8fa;
  min-height: 100vh;
}

.date-picker {
  display: flex;
  justify-content: space-around;
  align-items: center;
  padding: 12px 16px;
  background: #fff;
  position: sticky;
  top: 46px;
  z-index: 99;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
}

.date-range {
  padding: 8px 16px;
  background: #f7f8fa;
  text-align: center;
  font-size: 12px;
  color: #646566;
}

.loading-container,
.empty-container {
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 400px;
}

.device-list {
  padding: 8px 0;
}

.device-row {
  margin-bottom: 8px;
  background: #fff;
}

.device-title {
  display: flex;
  align-items: center;
  gap: 8px;
}

.device-name {
  font-size: 15px;
  font-weight: 500;
  color: #323233;
}

.device-info {
  font-size: 12px;
  color: #969799;
  margin-top: 4px;
  margin-bottom: 8px;
}

.timeline-container {
  margin-top: 8px;
}

.timeline {
  position: relative;
  height: 36px;
  background: #f5f5f5;
  border-radius: 4px;
  overflow: hidden;
}

.rental-block {
  position: absolute;
  top: 0;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 3px;
  cursor: pointer;
  transition: opacity 0.2s;
  overflow: hidden;
}

.rental-block:active {
  opacity: 0.8;
}

.rental-label {
  font-size: 11px;
  color: #fff;
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  padding: 0 4px;
}

.today-marker {
  position: absolute;
  top: 0;
  width: 2px;
  height: 100%;
  background: #ee0a24;
  z-index: 10;
  pointer-events: none;
}

.today-marker::before {
  content: '';
  position: absolute;
  top: -4px;
  left: -3px;
  width: 0;
  height: 0;
  border-left: 4px solid transparent;
  border-right: 4px solid transparent;
  border-top: 6px solid #ee0a24;
}

.rental-detail {
  padding-bottom: 20px;
}

.rental-detail .van-nav-bar {
  margin-bottom: 16px;
}
</style>
