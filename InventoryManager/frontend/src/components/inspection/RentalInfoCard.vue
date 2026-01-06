<template>
  <div class="rental-info-card">
    <el-card v-if="rental" shadow="never">
      <template #header>
        <div class="card-header">
          <span>租赁信息</span>
          <el-tag :type="getStatusType(rental.status)">
            {{ getStatusText(rental.status) }}
          </el-tag>
        </div>
      </template>
      
      <el-descriptions :column="1" border size="large">
        <el-descriptions-item label="客户姓名">
          {{ rental.customer_name }}
        </el-descriptions-item>
        
        <el-descriptions-item label="设备名称">
          {{ rental.device?.name || '-' }}
        </el-descriptions-item>
        
        <el-descriptions-item label="设备型号">
          {{ rental.device?.device_model?.display_name || rental.device?.model || '-' }}
        </el-descriptions-item>
        
        <el-descriptions-item label="租赁时间">
          {{ formatDate(rental.start_date) }} ~ {{ formatDate(rental.end_date) }}
        </el-descriptions-item>
        
        <el-descriptions-item v-if="rental.includes_handle" label="配套附件">
          <el-tag size="small" type="success">手柄</el-tag>
        </el-descriptions-item>
        
        <el-descriptions-item v-if="rental.includes_lens_mount" label="配套附件">
          <el-tag size="small" type="success">镜头支架</el-tag>
        </el-descriptions-item>
        
        <el-descriptions-item v-if="rental.accessories && rental.accessories.length > 0" label="库存附件">
          <div class="accessories-list">
            <el-tag 
              v-for="accessory in rental.accessories" 
              :key="accessory.id" 
              size="small" 
              type="info"
              style="margin-right: 8px; margin-bottom: 4px;"
            >
              {{ accessory.name }}
            </el-tag>
          </div>
        </el-descriptions-item>
        
        <el-descriptions-item v-if="rental.photo_transfer" label="代传照片">
          <el-tag size="small" type="warning">是</el-tag>
        </el-descriptions-item>
      </el-descriptions>
    </el-card>
    
    <el-empty v-else description="暂无租赁信息" />
  </div>
</template>

<script setup lang="ts">
import type { Rental } from '../../types/rental'
import { formatDisplayDate } from '../../utils/dateUtils'

// Props
interface Props {
  rental: Rental | null
}

defineProps<Props>()

// 方法
const formatDate = (dateStr: string) => {
  return formatDisplayDate(dateStr, 'YYYY-MM-DD')
}

const getStatusText = (status: string) => {
  const statusMap: Record<string, string> = {
    not_shipped: '待发货',
    scheduled_for_shipping: '已预约',
    shipped: '已发货',
    returned: '已收回',
    completed: '已完成',
    cancelled: '已取消'
  }
  return statusMap[status] || status
}

const getStatusType = (status: string) => {
  const typeMap: Record<string, any> = {
    not_shipped: 'info',
    scheduled_for_shipping: 'warning',
    shipped: 'success',
    returned: 'success',
    completed: '',
    cancelled: 'danger'
  }
  return typeMap[status] || 'info'
}
</script>

<style scoped>
.rental-info-card {
  margin-bottom: 20px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-weight: bold;
}

.accessories-list {
  display: flex;
  flex-wrap: wrap;
}

/* iPad 优化 */
@media (min-width: 768px) {
  :deep(.el-descriptions__label) {
    font-size: 16px;
  }
  
  :deep(.el-descriptions__content) {
    font-size: 16px;
  }
}
</style>
