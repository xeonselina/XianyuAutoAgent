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
          <el-button @click="printAll" type="success" :disabled="!canWrite">
            <el-icon><Printer /></el-icon>
            批量打印发货单
          </el-button>
          <el-button
            @click="showWaybillPrintDialog"
            type="primary"
            :disabled="!hasWaybills || !canWrite"
          >
            <el-icon><Printer /></el-icon>
            批量打印快递面单 ({{ waybillCount }})
          </el-button>
          <el-button
            @click="showScheduleDialog"
            type="warning"
            :disabled="selectedRentals.length === 0 || !canWrite"
          >
            <el-icon><Clock /></el-icon>
            预约发货 ({{ selectedRentals.length }})
          </el-button>
        </div>
      </div>

      <el-table
        :data="groupedRentals"
        :span-method="customerSpan"
        border
        stripe
        :row-key="(row: any) => row.id"
        @selection-change="handleSelectionChange"
        @cell-mouse-enter="handleCellMouseEnter"
        @cell-mouse-leave="handleCellMouseLeave"
      >
        <el-table-column type="selection" width="44" :selectable="isSelectableRow" />
        <el-table-column label="设备名称" min-width="110" show-overflow-tooltip>
          <template #default="{ row }">
            {{ row.device?.name || '-' }}
          </template>
        </el-table-column>
        <el-table-column prop="customer_name" label="客户" min-width="120">
          <template #default="{ row }">
            <div v-for="name in customerNames(row)" :key="name" class="customer-name">{{ name }}</div>
            <el-tag v-if="shipmentRows(row).length > 1" size="small" class="multi-device-tag">一单多台</el-tag>
            <el-tooltip
              v-if="row.is_relay_shipping"
              :content="RELAY_SELECTION_REASON"
              placement="top"
            >
              <el-tag
                type="warning"
                effect="dark"
                size="small"
                class="relay-shipping-tag"
                data-testid="relay-shipping-tag"
              >
                接力寄出
              </el-tag>
            </el-tooltip>
          </template>
        </el-table-column>
        <el-table-column label="设备" min-width="130" show-overflow-tooltip>
          <template #default="{ row }">
            {{ row.device?.device_model?.name || row.device?.name || '-' }}
          </template>
        </el-table-column>
        <el-table-column prop="destination" label="地址" min-width="220" show-overflow-tooltip />
        <el-table-column label="状态" width="86">
          <template #default="{ row }">
            <el-tag v-if="row.status === 'shipped'" type="success" size="small">已发货</el-tag>
            <el-tag v-else-if="row.status === 'scheduled_for_shipping'" type="warning" size="small">预约发货</el-tag>
            <el-tag v-else type="info" size="small">待发货</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="设备状态" width="128">
          <template #default="{ row }">
            <span v-if="!row.has_previous_rental">-</span>
            <el-tag
              v-else-if="row.previous_rental_status === 'returned'"
              color="#7232dd"
              effect="dark"
              size="small"
            >
              寄回在途
            </el-tag>
            <el-tag v-else-if="row.previous_rental_completed" type="success" size="small">
              ✓ 设备在库
            </el-tag>
            <el-tag v-else type="danger" size="small">
              ⚠ 上一单未结束
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="ship_out_tracking_no" label="运单号" width="152" show-overflow-tooltip />
        <el-table-column label="快递类型" width="94">
          <template #default="{ row }">
            <el-select
              v-model="row.express_type_id"
              size="small"
              :disabled="!canWrite"
              @change="updateExpressType(row.id, row.express_type_id)"
            >
              <el-option :value="1" label="特快" />
              <el-option :value="2" label="标快" />
              <el-option :value="263" label="半日达" />
            </el-select>
          </template>
        </el-table-column>
        <el-table-column label="预约时间" width="116">
          <template #default="{ row }">
            {{ row.scheduled_ship_time ? formatDateTime(row.scheduled_ship_time) : '-' }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="64">
          <template #default="{ row }">
            <el-button
              v-if="row.status === 'scheduled_for_shipping' && row.ship_out_tracking_no"
              @click="printSingle(row.id)"
              type="primary"
              size="small"
              link
              :disabled="!canWrite"
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
        <p>将为 <strong>{{ selectedRentals.length }}</strong> 个选中的订单预约发货（运单号将自动生成）</p>
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
        <el-button type="primary" @click="confirmSchedule" :loading="scheduling" :disabled="!canWrite">
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
            打印完成: 地址联 {{ printResults.waybill_success_count }} 张 / 内容联 {{ printResults.slip_success_count }} 张 / 失败 {{ printResults.failed_count }} 台
          </template>
        </el-alert>

        <div v-if="printResults.failed_count > 0" class="failed-items">
          <h4>失败项目:</h4>
          <div
            v-for="result in printResults.results.filter((r: any) => !r.waybill_success || !r.slip_success)"
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
import { ref, computed, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ArrowLeft, Search, Printer, Clock } from '@element-plus/icons-vue'
import axios from 'axios'
import dayjs from 'dayjs'
import { useTenantStore } from '@/stores/tenant'

const router = useRouter()
const tenantStore = useTenantStore()

// State
const dateRange = ref<[Date, Date] | null>(null)
const rentals = ref<any[]>([])
const selectedRentals = ref<any[]>([])
const loading = ref(false)
const scheduleDialogVisible = ref(false)
const scheduledTime = ref<string>(dayjs().add(1, 'hour').format('YYYY-MM-DDTHH:mm:ss'))
const scheduling = ref(false)

// Waybill printing state
const waybillPrintDialogVisible = ref(false)
const printing = ref(false)
const printProgress = ref(0)
const printResults = ref<any>(null)
const RELAY_SELECTION_REASON = '接力订单由前一位客户直接寄出，无需在批量发货中处理'
let previewGeneration = 0

// Computed
// 统计预约发货状态且有运单号和预约时间的订单（用于打印面单）
const hasWaybills = computed(() => rentals.value.some(r => r.status === 'scheduled_for_shipping' && r.ship_out_tracking_no && r.scheduled_ship_time))
const waybillCount = computed(() => new Set(rentals.value.filter(r => r.status === 'scheduled_for_shipping' && r.ship_out_tracking_no && r.scheduled_ship_time).map(r => `${r.warehouse_id}:${r.ship_out_tracking_no}`)).size)
const canWrite = computed(() => tenantStore.currentWarehouseId !== 'all')

const ensureConcreteWarehouse = () => {
  try {
    return tenantStore.requireConcreteWarehouse()
  } catch (error: any) {
    ElMessage.warning(error.message)
    return null
  }
}

const rowsBelongToWarehouse = (rows: any[], warehouseId: number) => {
  if (rows.length === 0 || rows.some(row => row?.warehouse_id !== warehouseId)) {
    ElMessage.warning('记录不属于当前仓库')
    return false
  }
  return true
}

// Methods
const goBack = () => {
  router.push('/')
}

// Preserve group order while bringing every device in a parcel next to its peers.
const shipmentKey = (row: any) => row.shipping_group_id
  ? `warehouse:${row.warehouse_id}:group:${row.shipping_group_id}`
  : `rental:${row.id}`
const shipmentGroups = computed(() => {
  const groups = new Map<string, any[]>()
  for (const row of rentals.value) {
    const key = shipmentKey(row)
    if (!groups.has(key)) groups.set(key, [])
    groups.get(key)!.push(row)
  }
  return groups
})
const groupedRentals = computed(() => [...shipmentGroups.value.values()].flat())
const shipmentRows = (row: any) => shipmentGroups.value.get(shipmentKey(row)) || [row]
const customerNames = (row: any) => [...new Set(shipmentRows(row).map(member => member.customer_name || '-'))]
const customerSpan = ({ row, column }: any) => {
  if (column.property !== 'customer_name') return [1, 1]
  const members = shipmentRows(row)
  return members[0].id === row.id ? [members.length, 1] : [0, 0]
}

// Selection handlers
const handleSelectionChange = (selection: any[]) => {
  selectedRentals.value = selection.filter(isSelectableRow)
}

const isSelectableRow = (row: any) => {
  return (
    canWrite.value &&
    row.warehouse_id === tenantStore.currentWarehouseId &&
    row.status !== 'shipped' &&
    row.status !== 'scheduled_for_shipping' &&
    !row.is_relay_shipping
  )
}

const handleCellMouseEnter = (row: any, column: any, cell: HTMLElement) => {
  if (column.type === 'selection' && row.is_relay_shipping) {
    cell.title = RELAY_SELECTION_REASON
  }
}

const handleCellMouseLeave = (_row: any, column: any, cell: HTMLElement) => {
  if (column.type === 'selection') {
    cell.removeAttribute('title')
  }
}

const previewOrders = async () => {
  if (!dateRange.value) {
    ElMessage.warning('请选择日期范围')
    return
  }

  const requestGeneration = ++previewGeneration
  rentals.value = []
  selectedRentals.value = []
  let warehouseId: number | 'all' | undefined
  try {
    loading.value = true
    await tenantStore.initialize()
    if (requestGeneration !== previewGeneration) return
    const [start, end] = dateRange.value
    warehouseId = tenantStore.currentWarehouseId
    const response = await axios.get('/api/rentals/by-ship-date', {
      params: {
        start_date: dayjs(start).format('YYYY-MM-DD'),
        end_date: dayjs(end).format('YYYY-MM-DD'),
        warehouse_id: warehouseId,
      }
    })

    if (
      requestGeneration === previewGeneration
      && warehouseId === tenantStore.currentWarehouseId
      && response.data.success
    ) {
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
    if (
      requestGeneration !== previewGeneration
      || (warehouseId !== undefined && warehouseId !== tenantStore.currentWarehouseId)
    ) return
    console.error('加载订单失败:', error)
    ElMessage.error('加载订单失败')
  } finally {
    if (requestGeneration === previewGeneration) loading.value = false
  }
}

const printAll = () => {
  const warehouseId = ensureConcreteWarehouse()
  if (warehouseId === null || !rowsBelongToWarehouse(rentals.value, warehouseId)) return
  if (!dateRange.value) return
  const [start, end] = dateRange.value
  const url = `/batch-shipping-order?start_date=${dayjs(start).format('YYYY-MM-DD')}&end_date=${dayjs(end).format('YYYY-MM-DD')}`
  // 在新标签页打开
  window.open(url, '_blank')
}

const showScheduleDialog = () => {
  if (ensureConcreteWarehouse() === null) return
  scheduleDialogVisible.value = true
}

const confirmSchedule = async () => {
  const warehouseId = ensureConcreteWarehouse()
  if (
    warehouseId === null
    || !rowsBelongToWarehouse(selectedRentals.value, warehouseId)
  ) return
  // 使用选中的订单
  const rentalIds = selectedRentals.value.map(r => r.id)

  if (rentalIds.length === 0) {
    ElMessage.warning('请先选择要预约发货的订单')
    return
  }

  try {
    scheduling.value = true
    const response = await axios.post('/api/shipping-batch/schedule', {
      rental_ids: rentalIds,
      scheduled_time: scheduledTime.value
    })

    if (response.data.success) {
      const { scheduled_count, shipment_count, failed_rentals, results } = response.data.data

      // 显示详细结果
      if (failed_rentals && failed_rentals.length > 0) {
        ElMessage.warning(`预约完成: 成功 ${scheduled_count} 个，失败 ${failed_rentals.length} 个`)
      } else {
        ElMessage.success(`成功预约 ${shipment_count} 票，共 ${scheduled_count} 台设备`)
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
  const warehouseId = ensureConcreteWarehouse()
  const rental = rentals.value.find(row => row.id === rentalId)
  if (warehouseId === null || !rowsBelongToWarehouse([rental], warehouseId)) return
  try {
    const response = await axios.patch('/api/shipping-batch/express-type', {
      rental_id: rentalId,
      express_type_id: expressTypeId
    })

    if (response.data.success) {
      ElMessage.success('快递类型已更新')
      await previewOrders()
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
  const warehouseId = ensureConcreteWarehouse()
  if (warehouseId === null) return
  // 只打印预约发货状态且有运单号和预约时间的订单
  const printableRentals = rentals.value
    .filter(r => r.status === 'scheduled_for_shipping' && r.ship_out_tracking_no && r.scheduled_ship_time)
  if (!rowsBelongToWarehouse(printableRentals, warehouseId)) return
  const rentalIds = printableRentals
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
        ElMessage.success(`成功打印 ${printResults.value.waybill_success_count} 个面单`)
        // 全部成功，2秒后自动关闭
        setTimeout(() => {
          if (printResults.value?.failed_count === 0) {
            closeWaybillPrintDialog()
          }
        }, 2000)
      } else {
        ElMessage.warning(
          `打印完成: 成功 ${printResults.value.waybill_success_count} 个，失败 ${printResults.value.failed_count} 个`
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

watch(() => tenantStore.currentWarehouseId, () => {
  selectedRentals.value = []
  rentals.value = []
  if (dateRange.value) void previewOrders()
  else rentals.value = []
}, { flush: 'sync' })

// Individual Print Method
const printSingle = async (rentalId: number) => {
  const warehouseId = ensureConcreteWarehouse()
  const rental = rentals.value.find(row => row.id === rentalId)
  if (warehouseId === null || !rowsBelongToWarehouse([rental], warehouseId)) return
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
  width: 100%;
  min-width: 0;
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
  flex-wrap: wrap;
  gap: 15px;
  align-items: center;
}

.date-inputs :deep(.el-date-editor) {
  flex: 0 1 360px;
  max-width: 100%;
}

.orders-table {
  margin-top: 20px;
}

.table-header {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 15px;
}

.table-header h3 {
  margin: 0;
}

.actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.orders-table :deep(.el-table .cell) {
  padding: 0 8px;
}

.customer-name {
  overflow-wrap: anywhere;
}

.multi-device-tag {
  margin-top: 6px;
}

.actions :deep(.el-button + .el-button) {
  margin-left: 0;
}

.relay-shipping-tag {
  margin-top: 4px;
  cursor: help;
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
