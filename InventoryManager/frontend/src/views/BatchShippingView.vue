<template>
  <div class="batch-shipping-view">
    <div class="header">
      <h1>批量发货管理</h1>
      <el-button @click="goBack" type="primary">
        <el-icon><ArrowLeft /></el-icon>
        返回甘特图
      </el-button>
    </div>

    <!-- Date Range Selection -->
    <el-card class="date-selector">
      <h3>选择发货日期范围</h3>
      <div class="date-inputs">
        <el-date-picker
          v-model="dateRange"
          type="daterange"
          range-separator="至"
          start-placeholder="开始日期"
          end-placeholder="结束日期"
          format="YYYY-MM-DD"
        />
        <el-button type="primary" @click="previewOrders" :loading="loading">
          <el-icon><Search /></el-icon>
          预览订单
        </el-button>
      </div>
    </el-card>

    <!-- Orders Table -->
    <el-card v-if="rentals.length > 0" class="orders-table">
      <div class="table-header">
        <h3>订单列表 (共 {{ rentals.length }} 个)</h3>
        <div class="actions">
          <el-button @click="printAll" type="success">
            <el-icon><Printer /></el-icon>
            批量打印发货单
          </el-button>
          <el-button
            @click="showWaybillPrintDialog"
            type="primary"
            :disabled="!hasWaybills"
          >
            <el-icon><Printer /></el-icon>
            批量打印快递面单 ({{ waybillCount }})
          </el-button>
          <el-button
            @click="showScheduleDialog"
            type="warning"
            :disabled="!hasUnshipped"
          >
            <el-icon><Clock /></el-icon>
            预约发货 ({{ unshippedCount }})
          </el-button>
        </div>
      </div>

      <el-table :data="rentals" border stripe>
        <el-table-column label="设备名称" width="80">
          <template #default="{ row }">
            {{ row.device?.name || '-' }}
          </template>
        </el-table-column>
        <el-table-column prop="customer_name" label="客户" width="120" />
        <el-table-column label="设备" width="180">
          <template #default="{ row }">
            {{ row.device?.device_model?.name || row.device?.name || '-' }}
          </template>
        </el-table-column>
        <el-table-column prop="destination" label="地址" min-width="260" show-overflow-tooltip />
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag v-if="row.status === 'shipped'" type="success">已发货</el-tag>
            <el-tag v-else-if="row.status === 'scheduled_for_shipping'" type="warning">预约发货</el-tag>
            <el-tag v-else type="info">待发货</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="ship_out_tracking_no" label="运单号" width="180" />
        <el-table-column label="快递类型" width="120">
          <template #default="{ row }">
            <el-select
              v-model="row.express_type_id"
              size="small"
              @change="updateExpressType(row.id, row.express_type_id)"
            >
              <el-option :value="1" label="特快" />
              <el-option :value="2" label="标快" />
              <el-option :value="6" label="半日达" />
            </el-select>
          </template>
        </el-table-column>
        <el-table-column label="预约时间" width="180">
          <template #default="{ row }">
            {{ row.scheduled_ship_time ? formatDateTime(row.scheduled_ship_time) : '-' }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="100">
          <template #default="{ row }">
            <el-button
              v-if="row.status === 'scheduled_for_shipping' && row.ship_out_tracking_no"
              @click="printSingle(row.id)"
              type="primary"
              size="small"
              link
            >
              <el-icon><Printer /></el-icon>
              打印
            </el-button>
          </template>
        </el-table-column>
      </el-table>

    </el-card>

    <!-- Schedule Shipping Dialog -->
    <el-dialog
      v-model="scheduleDialogVisible"
      title="预约发货"
      width="500px"
    >
      <div class="schedule-form">
        <p>将为 <strong>{{ unshippedCount }}</strong> 个未发货的订单预约发货（运单号将自动生成）</p>
        <el-form label-width="100px">
          <el-form-item label="发货时间:">
            <el-date-picker
              v-model="scheduledTime"
              type="datetime"
              placeholder="选择发货时间"
              format="YYYY-MM-DD HH:mm"
              value-format="YYYY-MM-DDTHH:mm:ss"
            />
          </el-form-item>
        </el-form>
      </div>

      <template #footer>
        <el-button @click="scheduleDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="confirmSchedule" :loading="scheduling">
          确认预约
        </el-button>
      </template>
    </el-dialog>

    <!-- Waybill Print Dialog -->
    <el-dialog
      v-model="waybillPrintDialogVisible"
      title="批量打印快递面单"
      width="600px"
      :close-on-click-modal="false"
    >
      <div v-if="printing" class="printing-status">
        <el-progress :percentage="printProgress" :status="printProgress === 100 ? 'success' : undefined" />
        <p style="text-align: center; margin-top: 10px">正在打印面单...</p>
      </div>

      <div v-if="printResults" class="print-results">
        <el-alert
          :type="printResults.failed_count === 0 ? 'success' : 'warning'"
          :closable="false"
        >
          <template #title>
            打印完成: 成功 {{ printResults.success_count }} / 失败 {{ printResults.failed_count }}
          </template>
        </el-alert>

        <div v-if="printResults.failed_count > 0" class="failed-items">
          <h4>失败项目:</h4>
          <div
            v-for="result in printResults.results.filter((r: any) => !r.success)"
            :key="result.rental_id"
            class="failed-item"
          >
            <span class="rental-id">订单 {{ result.rental_id }}:</span>
            <span class="error-msg">{{ result.message }}</span>
          </div>
        </div>
      </div>

      <template #footer>
        <el-button @click="closeWaybillPrintDialog">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ArrowLeft, Search, Printer, Clock } from '@element-plus/icons-vue'
import axios from 'axios'
import dayjs from 'dayjs'

const router = useRouter()

// State
const dateRange = ref<[Date, Date] | null>(null)
const rentals = ref<any[]>([])
const loading = ref(false)
const scheduleDialogVisible = ref(false)
const scheduledTime = ref<string>(dayjs().add(1, 'hour').format('YYYY-MM-DDTHH:mm:ss'))
const scheduling = ref(false)

// Waybill printing state
const waybillPrintDialogVisible = ref(false)
const printing = ref(false)
const printProgress = ref(0)
const printResults = ref<any>(null)

// Computed
// 统计未发货的订单（用于预约发货）- 排除已发货和已预约发货的订单
const hasUnshipped = computed(() => rentals.value.some(r => r.status !== 'shipped' && r.status !== 'scheduled_for_shipping'))
const unshippedCount = computed(() => rentals.value.filter(r => r.status !== 'shipped' && r.status !== 'scheduled_for_shipping').length)

// 统计预约发货状态且有运单号和预约时间的订单（用于打印面单）
const hasWaybills = computed(() => rentals.value.some(r => r.status === 'scheduled_for_shipping' && r.ship_out_tracking_no && r.scheduled_ship_time))
const waybillCount = computed(() => rentals.value.filter(r => r.status === 'scheduled_for_shipping' && r.ship_out_tracking_no && r.scheduled_ship_time).length)

// Methods
const goBack = () => {
  router.push('/')
}

const previewOrders = async () => {
  if (!dateRange.value) {
    ElMessage.warning('请选择日期范围')
    return
  }

  try {
    loading.value = true
    const [start, end] = dateRange.value
    const response = await axios.get('/api/rentals/by-ship-date', {
      params: {
        start_date: dayjs(start).format('YYYY-MM-DD'),
        end_date: dayjs(end).format('YYYY-MM-DD')
      }
    })

    if (response.data.success) {
      rentals.value = response.data.data.rentals.map((r: any) => ({
        ...r,
        express_type_id: r.express_type_id || 2  // 默认为标快
      }))
      if (rentals.value.length === 0) {
        ElMessage.info('该日期范围内未找到发货单')
      } else {
        ElMessage.success(`加载了 ${rentals.value.length} 个订单`)
      }
    }
  } catch (error: any) {
    console.error('加载订单失败:', error)
    ElMessage.error('加载订单失败')
  } finally {
    loading.value = false
  }
}

const printAll = () => {
  if (!dateRange.value) return
  const [start, end] = dateRange.value
  const url = `/batch-shipping-order?start_date=${dayjs(start).format('YYYY-MM-DD')}&end_date=${dayjs(end).format('YYYY-MM-DD')}`
  // 在新标签页打开
  window.open(url, '_blank')
}

const showScheduleDialog = () => {
  scheduleDialogVisible.value = true
}

const confirmSchedule = async () => {
  // 只预约未发货的订单
  const rentalIds = rentals.value
    .filter(r => r.status !== 'shipped')
    .map(r => r.id)

  if (rentalIds.length === 0) {
    ElMessage.warning('没有可预约的订单（已发货的订单不能重复预约）')
    return
  }

  try {
    scheduling.value = true
    const response = await axios.post('/api/shipping-batch/schedule', {
      rental_ids: rentalIds,
      scheduled_time: scheduledTime.value
    })

    if (response.data.success) {
      const { scheduled_count, failed_rentals, results } = response.data.data

      // 显示详细结果
      if (failed_rentals && failed_rentals.length > 0) {
        ElMessage.warning(`预约完成: 成功 ${scheduled_count} 个，失败 ${failed_rentals.length} 个`)
      } else {
        ElMessage.success(`成功预约 ${scheduled_count} 个订单，运单号已自动生成`)
      }

      scheduleDialogVisible.value = false
      // Refresh rentals
      previewOrders()
    }
  } catch (error: any) {
    console.error('预约发货失败:', error)
    ElMessage.error('预约发货失败')
  } finally {
    scheduling.value = false
  }
}

const formatDateTime = (dateStr: string) => {
  return dayjs(dateStr).format('MM-DD HH:mm')
}

const updateExpressType = async (rentalId: number, expressTypeId: number) => {
  try {
    const response = await axios.patch('/api/shipping-batch/express-type', {
      rental_id: rentalId,
      express_type_id: expressTypeId
    })

    if (response.data.success) {
      ElMessage.success('快递类型已更新')
    } else {
      ElMessage.error(response.data.message || '更新快递类型失败')
    }
  } catch (error: any) {
    console.error('更新快递类型失败:', error)
    ElMessage.error('更新快递类型失败')
  }
}

// Waybill Printing Methods
const showWaybillPrintDialog = async () => {
  // 只打印预约发货状态且有运单号和预约时间的订单
  const rentalIds = rentals.value
    .filter(r => r.status === 'scheduled_for_shipping' && r.ship_out_tracking_no && r.scheduled_ship_time)
    .map(r => r.id)

  if (rentalIds.length === 0) {
    ElMessage.warning('没有可打印的订单（需要先预约发货）')
    return
  }

  // 显示对话框并立即开始打印
  waybillPrintDialogVisible.value = true
  printResults.value = null
  printProgress.value = 0

  try {
    printing.value = true
    printProgress.value = 0

    const response = await axios.post('/api/shipping-batch/print-waybills', {
      rental_ids: rentalIds
      // 不传 printer_sn，使用后端默认打印机
    })

    printProgress.value = 100

    if (response.data.success) {
      printResults.value = response.data.data

      if (printResults.value.failed_count === 0) {
        ElMessage.success(`成功打印 ${printResults.value.success_count} 个面单`)
        // 全部成功，2秒后自动关闭
        setTimeout(() => {
          if (printResults.value?.failed_count === 0) {
            closeWaybillPrintDialog()
          }
        }, 2000)
      } else {
        ElMessage.warning(
          `打印完成: 成功 ${printResults.value.success_count} 个，失败 ${printResults.value.failed_count} 个`
        )
      }
    } else {
      ElMessage.error(response.data.message || '打印失败')
    }
  } catch (error: any) {
    console.error('打印快递面单失败:', error)
    ElMessage.error('打印快递面单失败')
  } finally {
    printing.value = false
  }
}

const closeWaybillPrintDialog = () => {
  waybillPrintDialogVisible.value = false
  printResults.value = null
  printProgress.value = 0
}

// Individual Print Method
const printSingle = async (rentalId: number) => {
  try {
    const response = await axios.post('/api/shipping-batch/print-waybills', {
      rental_ids: [rentalId]
    })

    if (response.data.success) {
      const result = response.data.data
      if (result.failed_count === 0) {
        ElMessage.success('面单打印成功')
      } else {
        const errorMsg = result.results[0]?.message || '打印失败'
        ElMessage.error(`打印失败: ${errorMsg}`)
      }
    } else {
      ElMessage.error(response.data.message || '打印失败')
    }
  } catch (error: any) {
    console.error('打印失败:', error)
    ElMessage.error('打印失败')
  }
}

// Lifecycle hooks removed - no scanning needed
</script>

<style scoped>
.batch-shipping-view {
  padding: 20px;
  max-width: 1400px;
  margin: 0 auto;
}

.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}

.header h1 {
  margin: 0;
  font-size: 28px;
  color: #303133;
}

.date-selector {
  margin-bottom: 20px;
}

.date-selector h3 {
  margin-top: 0;
  margin-bottom: 15px;
}

.date-inputs {
  display: flex;
  gap: 15px;
  align-items: center;
}

.orders-table {
  margin-top: 20px;
}

.table-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 15px;
}

.table-header h3 {
  margin: 0;
}

.actions {
  display: flex;
  gap: 10px;
}

.scan-instruction {
  margin-top: 20px;
}

.rental-details {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.detail-item {
  display: flex;
  padding: 8px 0;
  border-bottom: 1px solid #eee;
}

.detail-item .label {
  font-weight: 600;
  width: 100px;
  color: #606266;
}

.detail-item .value {
  flex: 1;
  color: #303133;
}

.detail-item .value.highlight {
  color: #409eff;
  font-weight: 600;
}

.schedule-form {
  padding: 20px 0;
}

.schedule-form p {
  margin-bottom: 20px;
  font-size: 15px;
}

.waybill-print-form {
  padding: 20px 0;
}

.waybill-print-form p {
  margin-bottom: 20px;
  font-size: 15px;
}

.printing-status {
  padding: 30px 0;
}

.print-results {
  padding: 20px 0;
}

.failed-items {
  margin-top: 20px;
  padding: 15px;
  background-color: #fef0f0;
  border-radius: 4px;
}

.failed-items h4 {
  margin: 0 0 10px 0;
  color: #f56c6c;
  font-size: 14px;
}

.failed-item {
  padding: 8px 0;
  border-bottom: 1px solid #fde2e2;
  display: flex;
  gap: 10px;
}

.failed-item:last-child {
  border-bottom: none;
}

.failed-item .rental-id {
  font-weight: 600;
  color: #606266;
  min-width: 100px;
}

.failed-item .error-msg {
  color: #f56c6c;
  flex: 1;
}
</style>
