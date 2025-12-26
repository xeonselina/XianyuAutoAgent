<template>
  <el-tooltip
    :visible="visible"
    :virtual-ref="triggerRef"
    virtual-triggering
    placement="top"
    popper-class="rental-tooltip"
    :show-after="0"
    :hide-after="0"
    :popper-options="{ strategy: 'fixed' }"
  >
    <template #content>
      <div 
        class="tooltip-content" 
        v-if="rental"
        @mouseenter="handleTooltipEnter"
        @mouseleave="handleTooltipLeave"
      >
        <div class="tooltip-header">
          <h4>{{ rental.device?.name }}</h4>
          <el-tag :type="getStatusType(rental.status)" size="small">
            {{ getStatusText(rental.status) }}
          </el-tag>
        </div>
        
        <div class="tooltip-body">
          <div class="info-row">
            <span class="label">闲鱼 ID:</span>
            <span class="value">{{ rental.customer_name || '未填写' }}</span>
          </div>
          
          <div class="info-row">
            <span class="label">开始日期:</span>
            <span class="value">{{ rental.start_date }}</span>
          </div>
          
          <div class="info-row">
            <span class="label">结束日期:</span>
            <span class="value">{{ rental.end_date }}</span>
          </div>
          
          <div class="info-row" v-if="rental.customer_phone">
            <span class="label">客户电话:</span>
            <span class="value">{{ rental.customer_phone }}</span>
          </div>
          
          <div class="info-row" v-if="rental.destination">
            <span class="label">收件信息:</span>
            <span class="value">{{ rental.destination }}</span>
          </div>
          
          <div class="info-row" v-if="rental.ship_out_tracking_no">
            <span class="label">寄出运单号:</span>
            <span class="value">{{ rental.ship_out_tracking_no }}</span>
          </div>
          
          <div class="info-row" v-if="rental.ship_in_tracking_no">
            <span class="label">寄回运单号:</span>
            <span class="value">{{ rental.ship_in_tracking_no }}</span>
          </div>
          
          <div class="info-row" v-if="rental.ship_out_time">
            <span class="label">寄出时间:</span>
            <span class="value">{{ formatDateTime(rental.ship_out_time) }}</span>
          </div>
          
          <div class="info-row" v-if="rental.ship_in_time">
            <span class="label">收回时间:</span>
            <span class="value">{{ formatDateTime(rental.ship_in_time) }}</span>
          </div>

          <div class="info-row" v-if="hasAccessories">
            <span class="label">包含附件:</span>
            <div class="accessories-list">
              <el-tag
                v-for="accessory in accessories"
                :key="accessory.id"
                type="info"
                size="small"
                class="accessory-tag"
              >
                {{ accessory.name }}
              </el-tag>
            </div>
          </div>
        </div>

        <!-- 档期冲突警告 -->
        <div v-if="conflictInfo?.hasConflict" class="conflict-warning-section">
          <div class="warning-header">⚠️ 档期冲突警告</div>
          <div class="warning-details">
            <p>下一个租赁距离本次结束仅 {{ conflictInfo.dayGap }} 天</p>
            <p>目的地: {{ conflictInfo.currentDestination || '未知' }} → {{ conflictInfo.nextDestination || '未知' }}</p>
            <p class="warning-suggestion">建议调整档期或确认物流时效</p>
          </div>
        </div>

        <div class="tooltip-footer">
          <div class="actions-hint">
            <span>单击编辑 · 双击删除</span>
          </div>
        </div>
      </div>
    </template>
  </el-tooltip>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { Rental } from '../stores/gantt'
import dayjs from 'dayjs'

interface ConflictInfo {
  hasConflict: boolean
  nextRentalId?: number
  dayGap?: number
  currentDestination?: string
  nextDestination?: string
}

interface Props {
  rental: Rental | null
  visible: boolean
  triggerRef?: HTMLElement
  conflictInfo?: ConflictInfo
}

const emit = defineEmits<{
  'tooltip-enter': []
  'tooltip-leave': []
}>()

const props = defineProps<Props>()

// Tooltip悬停事件处理
const handleTooltipEnter = () => {
  emit('tooltip-enter')
}

const handleTooltipLeave = () => {
  emit('tooltip-leave')
}

// 计算附件信息
const accessories = computed(() => {
  if (!props.rental) return []
  return props.rental.accessories || []
})

const hasAccessories = computed(() => {
  return accessories.value.length > 0
})

// 格式化日期时间（数据库存储的就是本地时间，直接格式化）
const formatDateTime = (dateTime: string) => {
  if (!dateTime) return ''
  // 直接使用 dayjs 格式化，不做时区转换
  return dayjs(dateTime).format('YYYY-MM-DD HH:mm')
}

// 获取状态类型
const getStatusType = (status: string) => {
  const typeMap: Record<string, string> = {
    'not_shipped': 'warning',
    'shipped': 'success',
    'returned': 'info',
    'completed': 'primary',
    'cancelled': 'danger'
  }
  return typeMap[status] || 'info'
}

// 获取状态文本
const getStatusText = (status: string) => {
  const textMap: Record<string, string> = {
    'not_shipped': '未发货',
    'shipped': '已发货',
    'returned': '已收回',
    'completed': '已完成',
    'cancelled': '已取消'
  }
  return textMap[status] || status
}
</script>

<style>
.rental-tooltip {
  max-width: 350px !important;
  padding: 0 !important;
  background: white !important;
  border: 1px solid var(--el-border-color) !important;
  border-radius: 8px !important;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15) !important;
  z-index: 9999 !important;
  pointer-events: auto !important;
}

.rental-tooltip .el-popper__arrow::before {
  border-top-color: var(--el-border-color) !important;
}
</style>

<style scoped>
.tooltip-content {
  padding: 16px;
  font-size: 13px;
  line-height: 1.4;
}

.tooltip-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--el-border-color-lighter);
}

.tooltip-header h4 {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.tooltip-body {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.info-row {
  display: flex;
  align-items: flex-start;
  gap: 8px;
}

.label {
  min-width: 80px;
  font-weight: 500;
  color: var(--el-text-color-secondary);
  flex-shrink: 0;
}

.value {
  color: var(--el-text-color-primary);
  word-break: break-all;
  flex: 1;
}

.tooltip-footer {
  margin-top: 12px;
  padding-top: 8px;
  border-top: 1px solid var(--el-border-color-lighter);
}

.actions-hint {
  text-align: center;
  font-size: 11px;
  color: var(--el-text-color-placeholder);
  font-style: italic;
}

.accessories-list {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.accessory-tag {
  font-size: 11px;
}

/* 档期冲突警告样式 */
.conflict-warning-section {
  margin-top: 12px;
  padding: 8px;
  border-radius: 4px;
  background-color: #FFF9E6;
  border: 1px solid #FFC107;
}

.warning-header {
  font-weight: 600;
  color: #FF6F00;
  margin-bottom: 4px;
  font-size: 13px;
}

.warning-details p {
  margin: 4px 0;
  font-size: 13px;
  color: var(--el-text-color-primary);
}

.warning-suggestion {
  color: #E65100;
  font-style: italic;
  font-size: 12px !important;
}
</style>
