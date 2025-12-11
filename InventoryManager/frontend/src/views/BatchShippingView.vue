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
            @click="showScheduleDialog"
            type="warning"
            :disabled="!hasWaybills"
          >
            <el-icon><Clock /></el-icon>
            预约发货 ({{ waybillCount }})
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
        <el-table-column label="状态" width="80">
          <template #default="{ row }">
            <el-tag v-if="row.status === 'shipped'" type="success">已发货</el-tag>
            <el-tag v-else-if="row.ship_out_tracking_no" type="warning">已录入运单</el-tag>
            <el-tag v-else type="info">未录入</el-tag>
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
      </el-table>

      <!-- Scanning Instruction -->
      <div class="scan-instruction">
        <el-alert type="info" :closable="false">
          <template #title>
            <strong>扫码操作说明</strong>
          </template>
          使用扫码枪扫描发货单上的二维码，系统将自动识别并提示录入运单号
        </el-alert>
      </div>
    </el-card>

    <!-- Rental Detail Dialog -->
    <el-dialog
      v-model="rentalDialogVisible"
      title="租赁详情 - 请扫描顺丰面单"
      width="600px"
      :close-on-click-modal="false"
    >
      <div v-if="currentRental" class="rental-details">
        <div class="detail-item">
          <span class="label">租赁ID:</span>
          <span class="value">{{ currentRental.rental_id }}</span>
        </div>
        <div class="detail-item">
          <span class="label">客户姓名:</span>
          <span class="value">{{ currentRental.customer_name }}</span>
        </div>
        <div class="detail-item">
          <span class="label">联系电话:</span>
          <span class="value">{{ currentRental.customer_phone }}</span>
        </div>
        <div class="detail-item">
          <span class="label">收货地址:</span>
          <span class="value">{{ currentRental.destination }}</span>
        </div>
        <div class="detail-item">
          <span class="label">租赁设备:</span>
          <span class="value">{{ currentRental.device_name }}</span>
        </div>
        <div class="detail-item" v-if="currentRental.accessories && currentRental.accessories.length > 0">
          <span class="label">附件:</span>
          <span class="value">{{ currentRental.accessories.join(', ') }}</span>
        </div>
        <div class="detail-item">
          <span class="label">租赁时间:</span>
          <span class="value">{{ currentRental.start_date }} 至 {{ currentRental.end_date }}</span>
        </div>
        <div class="detail-item" v-if="currentRental.ship_out_tracking_no">
          <span class="label">已录入运单:</span>
          <span class="value highlight">{{ currentRental.ship_out_tracking_no }}</span>
        </div>
      </div>

      <template #footer>
        <el-button @click="rentalDialogVisible = false">关闭</el-button>
      </template>
    </el-dialog>

    <!-- Schedule Shipping Dialog -->
    <el-dialog
      v-model="scheduleDialogVisible"
      title="预约发货"
      width="500px"
    >
      <div class="schedule-form">
        <p>将为 <strong>{{ waybillCount }}</strong> 个已录入运单的订单预约发货</p>
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
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
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
const currentRental = ref<any>(null)
const rentalDialogVisible = ref(false)
const scheduleDialogVisible = ref(false)
const scheduledTime = ref<string>(dayjs().add(1, 'hour').format('YYYY-MM-DDTHH:mm:ss'))
const scheduling = ref(false)

// Scanner state
const scanBuffer = ref('')
const scanTimeout = ref<ReturnType<typeof setTimeout> | null>(null)
const awaitingWaybill = ref(false)

// Computed
// 只统计未发货且有运单号的订单
const hasWaybills = computed(() => rentals.value.some(r => r.ship_out_tracking_no && r.status !== 'shipped'))
const waybillCount = computed(() => rentals.value.filter(r => r.ship_out_tracking_no && r.status !== 'shipped').length)

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
  // 只预约未发货且有运单号的订单
  const rentalIds = rentals.value
    .filter(r => r.ship_out_tracking_no && r.status !== 'shipped')
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
      const { scheduled_count, failed_rentals } = response.data.data
      ElMessage.success(`成功预约 ${scheduled_count} 个订单`)
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

// Barcode Scanner Handlers
const handleKeyDown = async (event: KeyboardEvent) => {
  // Clear existing timeout
  if (scanTimeout.value) {
    clearTimeout(scanTimeout.value)
  }

  // Handle Enter key (end of scan)
  if (event.key === 'Enter') {
    if (scanBuffer.value.length > 0) {
      await processScan(scanBuffer.value)
      scanBuffer.value = ''
    }
    return
  }

  // Accumulate characters (only single char keys)
  if (event.key.length === 1) {
    scanBuffer.value += event.key

    // Set timeout to clear buffer after 200ms of inactivity
    scanTimeout.value = setTimeout(() => {
      scanBuffer.value = ''
    }, 200)
  }
}

const processScan = async (value: string) => {
  console.log('Scanned:', value)

  // Pattern detection
  if (/^\d+$/.test(value)) {
    // Rental ID (pure digits)
    await handleRentalScan(parseInt(value))
  } else if (/^[A-Z0-9]{10,}$/i.test(value)) {
    // SF Waybill (alphanumeric, 10+ chars)
    if (awaitingWaybill.value && currentRental.value) {
      await handleWaybillScan(value)
    } else {
      ElMessage.warning('请先扫描租赁订单二维码')
    }
  } else {
    ElMessage.warning(`无法识别的扫码内容: ${value}`)
  }
}

const handleRentalScan = async (rentalId: number) => {
  try {
    const response = await axios.post('/api/shipping-batch/scan-rental', {
      rental_id: rentalId
    })

    if (response.data.success) {
      currentRental.value = response.data.data
      rentalDialogVisible.value = true
      awaitingWaybill.value = true

      // Voice prompt
      speak('请扫描顺丰面单')
    } else {
      ElMessage.error(response.data.message)
    }
  } catch (error: any) {
    ElMessage.error('查询租赁记录失败')
  }
}

const handleWaybillScan = async (waybillNo: string) => {
  if (!currentRental.value) return

  try {
    const response = await axios.post('/api/shipping-batch/record-waybill', {
      rental_id: currentRental.value.rental_id,
      waybill_no: waybillNo
    })

    if (response.data.success) {
      ElMessage.success('运单号已录入')
      rentalDialogVisible.value = false
      awaitingWaybill.value = false
      currentRental.value = null

      // Voice prompt
      speak('已录入')

      // Refresh rentals
      previewOrders()
    } else {
      ElMessage.error(response.data.message)
    }
  } catch (error: any) {
    ElMessage.error('录入运单号失败')
  }
}

const speak = (text: string) => {
  if (!window.speechSynthesis) return

  const utterance = new SpeechSynthesisUtterance(text)
  utterance.lang = 'zh-CN'
  utterance.rate = 1.0
  window.speechSynthesis.speak(utterance)
}

// Lifecycle
onMounted(() => {
  document.addEventListener('keydown', handleKeyDown)
})

onUnmounted(() => {
  document.removeEventListener('keydown', handleKeyDown)
  if (scanTimeout.value) {
    clearTimeout(scanTimeout.value)
  }
})
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
</style>
