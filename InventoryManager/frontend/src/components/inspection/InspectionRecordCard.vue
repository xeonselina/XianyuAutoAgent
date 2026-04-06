<template>
  <el-card class="inspection-record-card" shadow="hover">
    <div class="card-header">
      <div class="device-info">
        <span class="device-name">设备: {{ record.device?.name || '未知设备' }}</span>
        <el-tag :type="statusType" size="small">
          {{ statusText }}
        </el-tag>
      </div>
      <div class="record-time">
        {{ formatDate(record.created_at) }}
      </div>
    </div>
    
    <div class="card-body">
      <div class="info-row">
        <span class="label">客户:</span>
        <span class="value">{{ record.rental?.customer_name || '-' }}</span>
      </div>
      <div class="info-row">
        <span class="label">电话:</span>
        <span class="value">{{ record.rental?.customer_phone || '-' }}</span>
      </div>
      <div class="info-row">
        <span class="label">租赁状态:</span>
        <span class="value">
          <el-tag :type="rentalStatusType" size="small">
            {{ rentalStatusText }}
          </el-tag>
        </span>
      </div>
      <div class="info-row">
        <span class="label">检查项:</span>
        <span class="value">
          {{ record.check_items?.filter((item: any) => item.is_checked).length || 0 }} / 
          {{ record.check_items?.length || 0 }} 已完成
        </span>
      </div>
      
      <!-- 异常项列表 -->
      <div v-if="abnormalItems.length > 0" class="abnormal-section">
        <div class="abnormal-title">
          <el-icon color="#E6A23C"><WarningFilled /></el-icon>
          <span>异常项 ({{ abnormalItems.length }})</span>
        </div>
        <ul class="abnormal-list">
          <li v-for="item in abnormalItems" :key="item.id" class="abnormal-item">
            <el-icon size="14"><Close /></el-icon>
            <span>{{ item.item_name }}</span>
          </li>
        </ul>
      </div>
    </div>
    
    <div class="card-footer">
      <el-button 
        v-if="record.rental && record.rental.status !== 'completed' && record.rental.status !== 'cancelled'"
        size="small" 
        type="success" 
        :loading="completingDeposit"
        @click="handleCompleteDeposit"
      >
        完成退押
      </el-button>
      <el-tag v-else-if="record.rental?.status === 'completed'" type="success" size="small">
        已完成
      </el-tag>
      <el-button size="small" @click="$emit('view', record)">
        查看详情
      </el-button>
      <el-button size="small" type="primary" @click="$emit('edit', record)">
        编辑
      </el-button>
    </div>
  </el-card>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import type { InspectionRecord } from '../../types/inspection'
import dayjs from 'dayjs'
import { WarningFilled, Close } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'

interface Props {
  record: InspectionRecord
}

const props = defineProps<Props>()

// Emits
const emit = defineEmits<{
  view: [record: InspectionRecord]
  edit: [record: InspectionRecord]
  'deposit-completed': [record: InspectionRecord]
}>()

// 状态
const completingDeposit = ref(false)

// 计算属性
const statusType = computed(() => {
  return props.record.status === 'normal' ? 'success' : 'warning'
})

const statusText = computed(() => {
  return props.record.status === 'normal' ? '验机正常' : '验机异常'
})

// 租赁状态
const rentalStatusText = computed(() => {
  const statusMap: Record<string, string> = {
    not_shipped: '待发货',
    scheduled_for_shipping: '已预约',
    shipped: '已发货',
    returned: '已收回',
    completed: '已完成',
    cancelled: '已取消'
  }
  return statusMap[props.record.rental?.status || ''] || props.record.rental?.status || '-'
})

const rentalStatusType = computed(() => {
  const typeMap: Record<string, string> = {
    not_shipped: 'info',
    scheduled_for_shipping: 'warning',
    shipped: '',
    returned: 'success',
    completed: 'success',
    cancelled: 'danger'
  }
  return typeMap[props.record.rental?.status || ''] || 'info'
})

// 获取未勾选的异常项
const abnormalItems = computed(() => {
  if (!props.record.check_items) return []
  return props.record.check_items.filter((item: any) => !item.is_checked)
})

const formatDate = (dateString: string) => {
  return dayjs(dateString).format('YYYY-MM-DD HH:mm')
}

// 完成退押
const handleCompleteDeposit = async () => {
  try {
    await ElMessageBox.confirm(
      `确认将设备 ${props.record.device?.name || ''} 的租赁标记为已完成？`,
      '完成退押',
      {
        confirmButtonText: '确认',
        cancelButtonText: '取消',
        type: 'warning'
      }
    )
    
    completingDeposit.value = true
    
    const response = await fetch(`/api/rentals/${props.record.rental_id}/status`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status: 'completed' })
    })
    const result = await response.json()
    
    if (result.success) {
      ElMessage.success('退押完成')
      emit('deposit-completed', props.record)
    } else {
      ElMessage.error(result.message || '操作失败')
    }
  } catch (error: any) {
    if (error !== 'cancel' && error?.toString() !== 'cancel') {
      ElMessage.error('操作失败')
    }
  } finally {
    completingDeposit.value = false
  }
}
</script>

<style scoped>
.inspection-record-card {
  margin-bottom: 16px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.device-info {
  display: flex;
  align-items: center;
  gap: 8px;
}

.device-name {
  font-size: 16px;
  font-weight: bold;
  color: #303133;
}

.record-time {
  font-size: 12px;
  color: #909399;
}

.card-body {
  margin-bottom: 12px;
}

.info-row {
  display: flex;
  margin-bottom: 8px;
  font-size: 14px;
}

.label {
  color: #909399;
  min-width: 60px;
}

.value {
  color: #606266;
}

.abnormal-section {
  margin-top: 12px;
  padding: 12px;
  background-color: #fef0f0;
  border-left: 3px solid #E6A23C;
  border-radius: 4px;
}

.abnormal-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 14px;
  font-weight: bold;
  color: #E6A23C;
  margin-bottom: 8px;
}

.abnormal-list {
  list-style: none;
  padding: 0;
  margin: 0;
}

.abnormal-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 0;
  font-size: 13px;
  color: #606266;
}

.abnormal-item .el-icon {
  color: #F56C6C;
  flex-shrink: 0;
}

.card-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}

/* iPad 优化 */
@media (min-width: 768px) {
  .device-name {
    font-size: 18px;
  }
  
  .info-row {
    font-size: 16px;
  }
  
  .abnormal-title {
    font-size: 15px;
  }
  
  .abnormal-item {
    font-size: 14px;
  }
}

/* 移动端优化 */
@media (max-width: 767px) {
  .card-header {
    flex-direction: column;
    align-items: flex-start;
    gap: 8px;
  }
  
  .abnormal-section {
    padding: 10px;
  }
  
  .abnormal-title {
    font-size: 13px;
  }
  
  .abnormal-item {
    font-size: 12px;
  }
}
</style>
