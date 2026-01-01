<template>
  <div class="booking-view">
    <van-nav-bar title="预约档期" fixed />
    
    <div class="booking-content">
      <van-form @submit="onSubmit">
        <!-- 设备选择 -->
        <van-cell-group inset title="设备信息">
          <van-field
            v-model="deviceName"
            label="选择设备"
            placeholder="点击选择设备"
            readonly
            right-icon="arrow"
            required
            @click="showDevicePicker = true"
          />
          
          <van-field
            v-if="form.device_id"
            label="设备型号"
            :value="selectedDevice?.model || '-'"
            readonly
          />
        </van-cell-group>

        <!-- 租赁日期 -->
        <van-cell-group inset title="租赁日期">
          <van-field
            v-model="startDateDisplay"
            label="开始日期"
            placeholder="选择开始日期"
            readonly
            right-icon="calendar-o"
            required
            @click="showStartDatePicker = true"
          />
          
          <van-field
            v-model="endDateDisplay"
            label="结束日期"
            placeholder="选择结束日期"
            readonly
            right-icon="calendar-o"
            required
            @click="showEndDatePicker = true"
          />
          
          <van-field
            v-if="form.start_date && form.end_date"
            label="租赁天数"
            :value="`${calculateDuration()} 天`"
            readonly
          />
        </van-cell-group>

        <!-- 客户信息 -->
        <van-cell-group inset title="客户信息">
          <van-field
            v-model="form.customer_name"
            label="客户名称"
            placeholder="请输入客户名称"
            required
            :rules="[{ required: true, message: '请输入客户名称' }]"
          />
          
          <van-field
            v-model="form.customer_phone"
            label="联系电话"
            placeholder="请输入联系电话"
            type="tel"
            required
            :rules="[
              { required: true, message: '请输入联系电话' },
              { pattern: /^1[3-9]\d{9}$/, message: '请输入正确的手机号' }
            ]"
          />
          
          <van-field
            v-model="form.destination"
            label="目的地"
            placeholder="请输入目的地"
            required
            :rules="[{ required: true, message: '请输入目的地' }]"
          />
        </van-cell-group>

        <!-- 订单信息(可选) -->
        <van-cell-group inset title="订单信息(可选)">
          <van-field
            v-model="form.xianyu_order_no"
            label="闲鱼订单号"
            placeholder="请输入闲鱼订单号"
          />
          
          <van-field
            v-model="orderAmountInput"
            label="订单金额"
            placeholder="请输入订单金额"
            type="number"
          />
        </van-cell-group>

        <!-- 提交按钮 -->
        <div class="submit-container">
          <van-button 
            round 
            block 
            type="primary" 
            native-type="submit"
            :loading="submitting"
          >
            创建租赁
          </van-button>
          
          <van-button 
            round 
            block 
            plain 
            type="default"
            @click="onReset"
          >
            重置
          </van-button>
        </div>
      </van-form>
    </div>

    <!-- 设备选择器 -->
    <van-popup v-model:show="showDevicePicker" position="bottom">
      <van-picker
        :columns="deviceColumns"
        @confirm="onDeviceConfirm"
        @cancel="showDevicePicker = false"
      />
    </van-popup>

    <!-- 开始日期选择器 -->
    <van-popup v-model:show="showStartDatePicker" position="bottom">
      <van-date-picker
        v-model="startDate"
        title="选择开始日期"
        :min-date="minDate"
        :max-date="maxDate"
        @confirm="onStartDateConfirm"
        @cancel="showStartDatePicker = false"
      />
    </van-popup>

    <!-- 结束日期选择器 -->
    <van-popup v-model:show="showEndDatePicker" position="bottom">
      <van-date-picker
        v-model="endDate"
        title="选择结束日期"
        :min-date="minDate"
        :max-date="maxDate"
        @confirm="onEndDateConfirm"
        @cancel="showEndDatePicker = false"
      />
    </van-popup>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useGanttStore } from '@/stores/gantt'
import { createRental, checkConflict } from '@/api/rental'
import dayjs from 'dayjs'
import type { Device, RentalFormData } from '@/types'
import { showToast, showDialog, showConfirmDialog } from 'vant'

const router = useRouter()
const ganttStore = useGanttStore()

// State
const form = ref<RentalFormData>({
  device_id: null,
  start_date: '',
  end_date: '',
  customer_name: '',
  customer_phone: '',
  destination: '',
  xianyu_order_no: '',
  order_amount: undefined
})

const submitting = ref(false)
const showDevicePicker = ref(false)
const showStartDatePicker = ref(false)
const showEndDatePicker = ref(false)

const deviceName = ref('')
const startDateDisplay = ref('')
const endDateDisplay = ref('')
const orderAmountInput = ref('')

// 日期选择器的值
const startDate = ref<string[]>([])
const endDate = ref<string[]>([])
const minDate = new Date(2020, 0, 1)
const maxDate = new Date(2030, 11, 31)

// 生命周期
onMounted(() => {
  ganttStore.loadDevices()
  
  // 初始化日期为今天
  const today = dayjs()
  startDate.value = [
    today.format('YYYY'),
    today.format('MM'),
    today.format('DD')
  ]
  endDate.value = [
    today.add(7, 'day').format('YYYY'),
    today.add(7, 'day').format('MM'),
    today.add(7, 'day').format('DD')
  ]
})

// Computed
const selectedDevice = computed(() => {
  return ganttStore.allDevices.find(d => d.id === form.value.device_id)
})

const deviceColumns = computed(() => {
  return ganttStore.allDevices
    .filter(d => !d.is_accessory && d.status === 'online')
    .map(device => ({
      text: `${device.name} (${device.model})`,
      value: device.id
    }))
})

/**
 * 设备选择确认
 */
const onDeviceConfirm = ({ selectedOptions }: any) => {
  const option = selectedOptions[0]
  form.value.device_id = option.value
  deviceName.value = option.text
  showDevicePicker.value = false
}

/**
 * 开始日期确认
 */
const onStartDateConfirm = ({ selectedValues }: any) => {
  const dateStr = selectedValues.join('-')
  form.value.start_date = dateStr
  startDateDisplay.value = dayjs(dateStr).format('YYYY-MM-DD')
  showStartDatePicker.value = false
  
  // 自动调整结束日期(如果结束日期早于开始日期)
  if (form.value.end_date && dayjs(form.value.end_date).isBefore(dayjs(dateStr))) {
    const newEndDate = dayjs(dateStr).add(7, 'day')
    form.value.end_date = newEndDate.format('YYYY-MM-DD')
    endDateDisplay.value = newEndDate.format('YYYY-MM-DD')
    endDate.value = [
      newEndDate.format('YYYY'),
      newEndDate.format('MM'),
      newEndDate.format('DD')
    ]
  }
}

/**
 * 结束日期确认
 */
const onEndDateConfirm = ({ selectedValues }: any) => {
  const dateStr = selectedValues.join('-')
  
  // 验证结束日期不能早于开始日期
  if (form.value.start_date && dayjs(dateStr).isBefore(dayjs(form.value.start_date))) {
    showToast({
      message: '结束日期不能早于开始日期',
      position: 'top'
    })
    return
  }
  
  form.value.end_date = dateStr
  endDateDisplay.value = dayjs(dateStr).format('YYYY-MM-DD')
  showEndDatePicker.value = false
}

/**
 * 计算租赁天数
 */
const calculateDuration = () => {
  if (!form.value.start_date || !form.value.end_date) return 0
  
  const start = dayjs(form.value.start_date)
  const end = dayjs(form.value.end_date)
  return end.diff(start, 'day') + 1
}

/**
 * 表单提交
 */
const onSubmit = async () => {
  // 验证必填字段
  if (!form.value.device_id) {
    showToast({ message: '请选择设备', position: 'top' })
    return
  }
  
  if (!form.value.start_date || !form.value.end_date) {
    showToast({ message: '请选择租赁日期', position: 'top' })
    return
  }
  
  if (!form.value.customer_name) {
    showToast({ message: '请输入客户名称', position: 'top' })
    return
  }
  
  if (!form.value.customer_phone) {
    showToast({ message: '请输入联系电话', position: 'top' })
    return
  }
  
  if (!form.value.destination) {
    showToast({ message: '请输入目的地', position: 'top' })
    return
  }
  
  // 转换订单金额
  if (orderAmountInput.value) {
    form.value.order_amount = parseFloat(orderAmountInput.value)
  }
  
  submitting.value = true
  
  try {
    // 检查设备冲突
    const shipOutTime = dayjs(form.value.start_date).subtract(2, 'day').hour(9).minute(0).format('YYYY-MM-DD HH:mm:ss')
    const shipInTime = dayjs(form.value.end_date).add(2, 'day').hour(18).minute(0).format('YYYY-MM-DD HH:mm:ss')
    
    const conflictResponse = await checkConflict({
      device_id: form.value.device_id!,
      ship_out_time: shipOutTime,
      ship_in_time: shipInTime
    }) as any
    
    if (conflictResponse.success && conflictResponse.data.has_conflicts) {
      const confirmed = await showConfirmDialog({
        title: '检测到冲突',
        message: '该设备在选定的时间段内已有租赁记录,是否继续创建?',
      })
      
      if (!confirmed) {
        submitting.value = false
        return
      }
    }
    
    // 创建租赁
    const response = await createRental(form.value) as any
    
    if (response.success) {
      showDialog({
        title: '成功',
        message: '租赁创建成功!'
      }).then(() => {
        // 刷新甘特图数据并跳转
        ganttStore.refreshData()
        router.push('/gantt')
      })
    } else {
      throw new Error(response.error || '创建租赁失败')
    }
  } catch (err: any) {
    showToast({
      message: err.message || '创建失败,请重试',
      position: 'top'
    })
    console.error('Failed to create rental:', err)
  } finally {
    submitting.value = false
  }
}

/**
 * 重置表单
 */
const onReset = () => {
  form.value = {
    device_id: null,
    start_date: '',
    end_date: '',
    customer_name: '',
    customer_phone: '',
    destination: '',
    xianyu_order_no: '',
    order_amount: undefined
  }
  
  deviceName.value = ''
  startDateDisplay.value = ''
  endDateDisplay.value = ''
  orderAmountInput.value = ''
  
  showToast({
    message: '已重置表单',
    position: 'top'
  })
}
</script>

<style scoped>
.booking-view {
  padding-top: 46px;
  padding-bottom: 50px;
  min-height: 100vh;
  background: #f7f8fa;
}

.booking-content {
  padding: 16px 0;
}

.submit-container {
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

:deep(.van-cell-group__title) {
  padding: 16px;
  font-weight: 500;
  color: #323233;
}

:deep(.van-field__label) {
  width: 90px;
}
</style>
