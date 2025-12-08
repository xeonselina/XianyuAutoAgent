<template>
  <el-dialog
    v-model="dialogVisible"
    title="批量打印发货单"
    width="600px"
    :close-on-click-modal="false"
    @close="handleClose"
  >
    <el-form
      ref="formRef"
      :model="form"
      label-width="120px"
    >
      <!-- 日期范围选择 -->
      <el-form-item label="开始日期">
        <VueDatePicker
          v-model="form.startDate"
          placeholder="选择开始日期"
          :format="'yyyy-MM-dd'"
          :locale="'zh-cn'"
          :week-start="1"
          :enable-time-picker="false"
          auto-apply
          style="width: 100%"
        />
      </el-form-item>

      <el-form-item label="结束日期">
        <VueDatePicker
          v-model="form.endDate"
          placeholder="选择结束日期"
          :format="'yyyy-MM-dd'"
          :locale="'zh-cn'"
          :week-start="1"
          :enable-time-picker="false"
          auto-apply
          style="width: 100%"
          :min-date="form.startDate || undefined"
        />
      </el-form-item>

      <!-- 预览按钮 -->
      <el-form-item>
        <el-button
          type="primary"
          @click="handlePreview"
          :loading="loading"
          :disabled="!form.startDate || !form.endDate"
        >
          预览订单
        </el-button>
      </el-form-item>

      <!-- 错误提示 -->
      <el-alert
        v-if="error"
        type="error"
        :closable="false"
        style="margin-bottom: 16px"
      >
        {{ error }}
      </el-alert>

      <!-- 预览结果 -->
      <div v-if="previewOrders.length > 0" class="preview-section">
        <el-divider content-position="left">
          <span class="divider-title">预览结果 (共 {{ previewOrders.length }} 个订单)</span>
        </el-divider>

        <div class="order-list">
          <div
            v-for="order in previewOrders"
            :key="order.id"
            class="order-item"
          >
            <div class="order-info">
              <span class="order-customer">{{ order.customer_name }}</span>
              <span class="order-device">{{ order.device?.name || '未知设备' }}</span>
              <span class="order-time">{{ formatShipTime(order.ship_out_time) }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- 无订单提示 -->
      <el-alert
        v-if="previewed && previewOrders.length === 0"
        type="warning"
        :closable="false"
      >
        该日期范围内未找到发货单
      </el-alert>
    </el-form>

    <template #footer>
      <div class="dialog-footer">
        <el-button @click="handleClose">取消</el-button>
        <el-button
          type="primary"
          @click="handleStartPrint"
          :disabled="previewOrders.length === 0"
        >
          开始打印
        </el-button>
      </div>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { useRouter } from 'vue-router'
import dayjs from 'dayjs'
import axios from 'axios'
import VueDatePicker from '@vuepic/vue-datepicker'
import '@vuepic/vue-datepicker/dist/main.css'

// Props & Emits
interface Props {
  modelValue: boolean
}

const props = defineProps<Props>()
const emit = defineEmits<{
  'update:modelValue': [value: boolean]
}>()

// Router
const router = useRouter()

// Refs
const formRef = ref()
const dialogVisible = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value)
})

// Form State
const form = ref({
  startDate: new Date() as Date | null,
  endDate: new Date() as Date | null
})

// UI State
const loading = ref(false)
const error = ref<string | null>(null)
const previewed = ref(false)
const previewOrders = ref<any[]>([])

// Handlers
const handleClose = () => {
  dialogVisible.value = false
  // 重置状态
  form.value = {
    startDate: new Date(),
    endDate: new Date()
  }
  previewOrders.value = []
  previewed.value = false
  error.value = null
}

const handlePreview = async () => {
  try {
    error.value = null
    loading.value = true
    previewed.value = false

    if (!form.value.startDate || !form.value.endDate) {
      error.value = '请选择开始和结束日期'
      return
    }

    // 验证日期范围
    if (form.value.endDate < form.value.startDate) {
      error.value = '结束日期必须晚于开始日期'
      return
    }

    // 调用 API 预览订单
    const startDateStr = dayjs(form.value.startDate).format('YYYY-MM-DD')
    const endDateStr = dayjs(form.value.endDate).format('YYYY-MM-DD')

    const response = await axios.get('/api/rentals/by-ship-date', {
      params: {
        start_date: startDateStr,
        end_date: endDateStr
      }
    })

    if (response.data.success) {
      previewOrders.value = response.data.data.rentals
      previewed.value = true

      if (previewOrders.value.length === 0) {
        ElMessage.warning('该日期范围内未找到发货单')
      } else {
        ElMessage.success(`找到 ${previewOrders.value.length} 个待打印订单`)
      }
    } else {
      error.value = response.data.message || '加载订单失败'
    }
  } catch (err: any) {
    console.error('预览订单失败:', err)
    error.value = err.response?.data?.message || '加载订单失败,请检查网络连接'
  } finally {
    loading.value = false
  }
}

const handleStartPrint = () => {
  if (previewOrders.value.length === 0) return

  const startDateStr = dayjs(form.value.startDate).format('YYYY-MM-DD')
  const endDateStr = dayjs(form.value.endDate).format('YYYY-MM-DD')

  // 导航到批量打印视图
  router.push({
    path: '/batch-shipping-order',
    query: {
      start_date: startDateStr,
      end_date: endDateStr
    }
  })

  handleClose()
}

const formatShipTime = (shipTime: string | null) => {
  if (!shipTime) return '未设置'
  return dayjs(shipTime).format('YYYY-MM-DD HH:mm')
}
</script>

<style scoped>
.dialog-footer {
  text-align: right;
}

.divider-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.preview-section {
  margin-top: 20px;
}

.order-list {
  max-height: 300px;
  overflow-y: auto;
}

.order-item {
  padding: 12px;
  border: 1px solid var(--el-border-color-light);
  border-radius: 4px;
  margin-bottom: 8px;
  background-color: var(--el-fill-color-blank);
}

.order-info {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
}

.order-customer {
  font-weight: 500;
  color: var(--el-text-color-primary);
}

.order-device {
  color: var(--el-text-color-regular);
  font-size: 14px;
}

.order-time {
  color: var(--el-text-color-secondary);
  font-size: 13px;
  white-space: nowrap;
}
</style>
