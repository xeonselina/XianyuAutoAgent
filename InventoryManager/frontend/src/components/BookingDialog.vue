<template>
  <el-dialog
    v-model="dialogVisible"
    title="预定设备"
    width="600px"
    :close-on-click-modal="false"
    @close="handleClose"
  >
    <el-form
      ref="formRef"
      :model="form"
      :rules="rules"
      label-width="120px"
      @submit.prevent="handleSubmit"
    >
      <el-form-item label="开始日期" prop="startDate">
        <VueDatePicker
          :model-value="form.startDate"
          @update:model-value="handleStartDateChange"
          :disabled-dates="disabledDate"
          placeholder="选择开始日期"
          :format="'yyyy-MM-dd'"
          :locale="'zh-cn'"
          :week-start="1"
          :enable-time-picker="false"
          auto-apply
          style="width: 100%"
        />
      </el-form-item>

      <el-form-item label="结束日期" prop="endDate">
        <VueDatePicker
          :model-value="form.endDate"
          @update:model-value="handleEndDateChange"
          :disabled-dates="disabledEndDate"
          placeholder="选择结束日期"
          :format="'yyyy-MM-dd'"
          :locale="'zh-cn'"
          :week-start="1"
          :enable-time-picker="false"
          auto-apply
          style="width: 100%"
        />
      </el-form-item>

      <el-form-item label="物流天数" prop="logisticsDays">
        <el-input-number
          v-model="form.logisticsDays"
          :min="1"
          :max="7"
          style="width: 100%"
        />
        <div class="form-tip">寄出和收回所需的物流时间</div>
      </el-form-item>

      <el-form-item label="选择设备" prop="selectedDeviceId">
        <div class="device-selection">
          <el-select
            v-model="form.selectedDeviceId"
            placeholder="请选择设备"
            style="flex: 1"
            clearable
          >
            <el-option
              v-for="device in availableDevices"
              :key="device.id"
              :label="device.name"
              :value="device.id"
            />
          </el-select>
          <el-button
            type="info"
            @click="findAvailableSlot"
            :loading="searching"
            :disabled="!canSearchSlot"
            style="margin-left: 8px"
          >
            查找档期
          </el-button>
        </div>
        <div class="form-tip">选择具体设备或点击查找档期自动匹配可用设备</div>
      </el-form-item>

      <el-form-item label="闲鱼ID" prop="customerName">
        <el-input
          v-model="form.customerName"
          placeholder="请输入闲鱼ID"
        />
      </el-form-item>

      <el-form-item label="客户电话" prop="customerPhone">
        <el-input
          v-model="form.customerPhone"
          placeholder="请输入手机号码"
          maxlength="11"
        />
      </el-form-item>

      <el-form-item label="收件信息" prop="destination">
        <el-input
          v-model="form.destination"
          type="textarea"
          :rows="3"
          placeholder="请填写详细的收件地址、收件人姓名等信息"
          @input="handleDestinationChange"
        />
        <div class="form-tip">系统会自动从收件信息中提取手机号码</div>
      </el-form-item>

      <!-- 可用档期显示 -->
      <el-form-item v-if="availableSlot" label="可用档期">
        <el-alert type="success" :closable="false">
          <template #title>
            <div class="slot-info">
              <div class="slot-device">
                <el-icon><Monitor /></el-icon>
                找到可用设备：{{ availableSlot.device.name }}
              </div>
              <div class="slot-times">
                <div>寄出时间：{{ formatDateTime(availableSlot.shipOutDate) }}</div>
                <div>收回时间：{{ formatDateTime(availableSlot.shipInDate) }}</div>
              </div>
            </div>
          </template>
        </el-alert>
      </el-form-item>
    </el-form>

    <template #footer>
      <div class="dialog-footer">
        <el-button @click="handleClose">取消</el-button>
        <el-button
          type="primary"
          @click="handleSubmit"
          :loading="submitting"
        >
          提交预定
        </el-button>
      </div>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { ref, reactive, computed, watch } from 'vue'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import { Monitor } from '@element-plus/icons-vue'
import { useGanttStore, type AvailableSlot } from '../stores/gantt'
import dayjs from 'dayjs'
import VueDatePicker from '@vuepic/vue-datepicker'
import '@vuepic/vue-datepicker/dist/main.css'
import { toAPIFormat } from '@/utils/dateUtils'

const props = defineProps<{
  modelValue: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  'success': []
}>()

const ganttStore = useGanttStore()

// 响应式状态
const formRef = ref<FormInstance>()
const searching = ref(false)
const submitting = ref(false)
const availableSlot = ref<AvailableSlot | null>(null)

// 表单数据
const form = reactive({
  startDate: null as Date | null,
  endDate: null as Date | null,
  logisticsDays: 1,
  selectedDeviceId: null as number | null,
  customerName: '',
  customerPhone: '',
  destination: ''
})

// 计算属性
const dialogVisible = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value)
})

const canSearchSlot = computed(() => {
  return form.startDate && form.endDate && form.logisticsDays > 0
})

const availableDevices = computed(() => {
  return ganttStore.devices || []
})

// 表单验证规则
const rules: FormRules = {
  startDate: [
    { required: true, message: '请选择开始日期', trigger: 'change' }
  ],
  endDate: [
    { required: true, message: '请选择结束日期', trigger: 'change' }
  ],
  logisticsDays: [
    { required: true, message: '请输入物流天数', trigger: 'change' }
  ],
  customerName: [
    { required: true, message: '请输入闲鱼ID', trigger: 'blur' }
  ],
  customerPhone: [
    { required: true, message: '请输入客户电话', trigger: 'blur' },
    { pattern: /^1[3-9]\d{9}$/, message: '请输入正确的手机号码', trigger: 'blur' }
  ],
  destination: [
    { required: true, message: '请输入收件信息', trigger: 'blur' }
  ]
}

// 监听日期变化已移到处理函数中

// 日期处理函数
const formatDateToString = (date: Date | null): string => {
  if (!date) return ''
  return dayjs(date).format('YYYY-MM-DD')
}

const handleStartDateChange = (date: Date | null) => {
  form.startDate = date
  // 如果结束日期早于开始日期，清空结束日期
  if (date && form.endDate && dayjs(form.endDate).isBefore(dayjs(date))) {
    form.endDate = null
  }
  // 重置可用档期
  availableSlot.value = null
}

const handleEndDateChange = (date: Date | null) => {
  form.endDate = date
  // 重置可用档期
  availableSlot.value = null
}

// 方法
const disabledDate = (date: Date) => {
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  return date < today
}

const disabledEndDate = (date: Date) => {
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  
  if (!form.startDate) {
    return date < today
  }
  
  const startDate = new Date(form.startDate)
  startDate.setHours(0, 0, 0, 0)
  
  return date < startDate || date < today
}

const handleDestinationChange = (value: string) => {
  // 自动提取手机号码
  const phoneMatch = value.match(/1[3-9]\d{9}/)
  if (phoneMatch && !form.customerPhone) {
    form.customerPhone = phoneMatch[0]
    ElMessage.success(`已自动提取手机号: ${phoneMatch[0]}`)
  }
}

const findAvailableSlot = async () => {
  if (!canSearchSlot.value) {
    ElMessage.warning('请先完善日期和物流信息')
    return
  }

  searching.value = true
  try {
    let result
    
    if (form.selectedDeviceId) {
      // 如果指定了设备，检查该设备的档期
      const selectedDevice = availableDevices.value.find(d => d.id === form.selectedDeviceId)
      if (!selectedDevice) {
        throw new Error('未找到选择的设备')
      }
      
      // 暂时使用通用的查找方法，后续可能需要扩展API支持指定设备
      result = await ganttStore.findAvailableSlot(
        formatDateToString(form.startDate),
        formatDateToString(form.endDate),
        form.logisticsDays
      )
      
      // 验证返回的设备是否是指定设备
      if (result.device.id !== form.selectedDeviceId) {
        throw new Error(`指定设备 ${selectedDevice.name} 在该时间段不可用`)
      }
    } else {
      // 未指定设备，自动查找可用设备
      result = await ganttStore.findAvailableSlot(
        formatDateToString(form.startDate),
        formatDateToString(form.endDate),
        form.logisticsDays
      )
      
      // 自动填入找到的设备
      form.selectedDeviceId = result.device.id
    }
    
    availableSlot.value = {
      device: result.device,
      shipOutDate: result.shipOutDate,
      shipInDate: result.shipInDate
    }
    
    ElMessage.success(result.message)
  } catch (error) {
    ElMessage.error((error as Error).message)
    availableSlot.value = null
  } finally {
    searching.value = false
  }
}

const handleSubmit = async () => {
  try {
    await formRef.value?.validate()
  } catch {
    return
  }

  // 如果没有查找档期，尝试直接提交但要检查冲突
  let deviceId = form.selectedDeviceId
  if (!availableSlot.value && !deviceId) {
    ElMessage.warning('请选择设备或查找可用档期')
    return
  }

  if (!deviceId && availableSlot.value) {
    deviceId = availableSlot.value.device.id
  }

  submitting.value = true
  try {
      const startDate = dayjs(form.startDate!)
      const endDate = dayjs(form.endDate!)
      const shipOutTime = toAPIFormat(startDate.subtract(form.logisticsDays, 'day').subtract(1, 'day').hour(9).minute(0).second(0))
      const shipInTime = toAPIFormat(endDate.add(form.logisticsDays, 'day').add(1, 'day').hour(18).minute(0).second(0))

    const rentalData = {
      device_id: deviceId!,
      start_date: formatDateToString(form.startDate),
      end_date: formatDateToString(form.endDate),
      customer_name: form.customerName,
      customer_phone: form.customerPhone,
      destination: form.destination,
      ship_out_time: shipOutTime,
      ship_in_time: shipInTime
    }

    await ganttStore.createRental(rentalData)
    emit('success')
    handleClose()
  } catch (error: any) {
    // 检查是否是档期冲突错误
    if (error.message && (error.message.includes('冲突') || error.message.includes('档期冲突'))) {
      await handleConflictConfirmation(error.message)
    } else {
      ElMessage.error('创建失败：' + error.message)
    }
  } finally {
    submitting.value = false
  }
}

const handleConflictConfirmation = async (conflictMessage: string) => {
  try {
    await ElMessageBox.confirm(
      `检测到档期冲突：${conflictMessage}\n\n是否仍要提交预定？`,
      '档期冲突确认',
      {
        type: 'warning',
        confirmButtonText: '确认提交',
        cancelButtonText: '取消'
      }
    )
    
    // 用户确认后，强制提交
    await forceSubmitRental()
  } catch {
    // 用户取消，不做任何操作
    ElMessage.info('已取消预定')
  }
}

const forceSubmitRental = async () => {
  const deviceId = form.selectedDeviceId || availableSlot.value?.device.id
  if (!deviceId) return

  // Calculate ship times based on logistics days if not from available slot
  let shipOutTime, shipInTime
  if (availableSlot.value) {
    shipOutTime = toAPIFormat(availableSlot.value.shipOutDate)
    shipInTime = toAPIFormat(availableSlot.value.shipInDate)
  } else {
    // Calculate based on logistics days - 寄出时间需要提前1天保证用户在开始前收到
    const startDate = dayjs(form.startDate!)
    const endDate = dayjs(form.endDate!)
    shipOutTime = toAPIFormat(startDate.subtract(form.logisticsDays, 'day').subtract(1, 'day').hour(9).minute(0).second(0))
    shipInTime = toAPIFormat(endDate.add(form.logisticsDays, 'day').hour(18).minute(0).second(0))
  }

  const rentalData = {
    device_id: deviceId,
    start_date: formatDateToString(form.startDate),
    end_date: formatDateToString(form.endDate),
    customer_name: form.customerName,
    customer_phone: form.customerPhone,
    destination: form.destination,
    ship_out_time: shipOutTime,
    ship_in_time: shipInTime,
    force_create: true // 强制创建标志
  }

  try {
    await ganttStore.createRental(rentalData)
    emit('success')
    handleClose()
    ElMessage.success('预定已成功提交')
  } catch (error: any) {
    ElMessage.error('强制创建失败：' + error.message)
  }
}

const handleClose = () => {
  // 重置表单
  formRef.value?.resetFields()
  availableSlot.value = null
  searching.value = false
  submitting.value = false
  
  // 重置表单数据
  Object.assign(form, {
    startDate: null,
    endDate: null,
    logisticsDays: 1,
    selectedDeviceId: null,
    customerName: '',
    customerPhone: '',
    destination: ''
  })
  
  emit('update:modelValue', false)
}

const formatDateTime = (date: Date) => {
  return dayjs(date).format('YYYY-MM-DD HH:mm')
}
</script>

<style scoped>
.form-tip {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-top: 4px;
}

.slot-info {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.slot-device {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
  color: var(--el-color-success);
}

.slot-times {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 14px;
}

.device-selection {
  display: flex;
  align-items: center;
  width: 100%;
}

.dialog-footer {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
}
</style>

