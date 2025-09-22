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
          :min="0"
          :max="7"
          style="width: 100%"
        />
        <div class="form-tip">寄出和收回所需的物流时间，0天表示当天取送</div>
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
          placeholder="请输入手机号码(可选)"
          maxlength="11"
        />
        <div class="form-tip">可选填写，也可在收件信息中提供</div>
      </el-form-item>

      <el-form-item label="收件信息" prop="destination">
        <el-input
          v-model="form.destination"
          type="textarea"
          :rows="3"
          placeholder="请填写详细的收件地址、收件人姓名等信息(可选)"
          @input="handleDestinationChange"
        />
        <div class="form-tip">可选填写，系统会自动从收件信息中提取手机号码</div>
      </el-form-item>

      <!-- 附件选择 -->
      <el-form-item label="附件选择" prop="selectedAccessoryIds">
        <div class="device-selection">
          <el-select
            v-model="form.selectedAccessoryIds"
            placeholder="选择附件(可多选)"
            clearable
            filterable
            multiple
            collapse-tags
            collapse-tags-tooltip
            style="flex: 1"
          >
            <el-option
              v-for="accessory in availableControllers"
              :key="accessory.id"
              :label="accessory.name"
              :value="accessory.id"
            >
              <span>{{ accessory.name }}</span>
              <span style="float: right; color: var(--el-text-color-secondary); font-size: 13px">
                {{ accessory.model }}
              </span>
            </el-option>
          </el-select>
          <el-button
            type="info"
            @click="findAvailableAccessory"
            :loading="searchingAccessory"
            :disabled="!canSearchSlot"
            style="margin-left: 8px"
          >
            查找附件
          </el-button>
        </div>
        <div class="form-tip">可选择多个附件或点击查找附件自动匹配可用附件</div>

        <!-- 查找到的附件信息 -->
        <div v-if="availableAccessorySlot" class="slot-info" style="margin-top: 12px">
          <div class="slot-device">
            <el-icon><Monitor /></el-icon>
            已找到可用附件: {{ availableAccessorySlot.accessory?.name || '未知附件' }}
          </div>
          <div class="slot-times">
            <div>寄出时间: {{ formatDateTime(availableAccessorySlot.shipOutDate) }}</div>
            <div>收回时间: {{ formatDateTime(availableAccessorySlot.shipInDate) }}</div>
          </div>
          <el-button
            type="primary"
            size="small"
            style="margin-top: 8px"
            @click="addFoundAccessory"
          >
            添加此附件
          </el-button>
        </div>
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
import { ref, reactive, computed, watch, nextTick } from 'vue'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import { Monitor, WarningFilled } from '@element-plus/icons-vue'
import { useGanttStore, type AvailableSlot } from '../stores/gantt'
import dayjs from 'dayjs'
import VueDatePicker from '@vuepic/vue-datepicker'
import '@vuepic/vue-datepicker/dist/main.css'
import { toAPIFormat } from '@/utils/dateUtils'
import axios from 'axios'

const props = defineProps<{
  modelValue: boolean
  selectedDeviceModel?: string
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
const searchingAccessory = ref(false)
const availableAccessorySlot = ref<{ accessory: any; shipOutDate: Date; shipInDate: Date } | null>(null)

// 表单数据
const form = reactive({
  startDate: null as Date | null,
  endDate: null as Date | null,
  logisticsDays: 1,
  selectedDeviceId: null as number | null,
  customerName: '',
  customerPhone: '',
  destination: '',
  selectedAccessoryIds: [] as number[],
  needController: false
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
  return ganttStore.devices?.filter(device => !device.is_accessory) || []
})

const availableControllers = ref<any[]>([])

// 在组件加载时获取附件列表
const loadAvailableControllers = async () => {
  try {
    const devicesResponse = await axios.get('/api/devices')
    if (devicesResponse.data.success) {
      const allDevices = devicesResponse.data.data
      availableControllers.value = allDevices.filter((device: any) => 
        device.is_accessory && device.model && device.model.includes('controller')
      )
    }
  } catch (error) {
    console.error('获取附件列表失败:', error)
  }
}

// 可用手柄状态（异步计算）
const controllerAvailabilityState = ref({
  checked: false,
  hasAvailable: false,
  count: 0,
  availableControllers: [] as any[]
})

const hasAvailableControllers = computed(() => {
  if (!availableControllers.value.length) return false
  
  // 如果有查找到的档期信息，优先使用它的手柄信息
  if (availableSlot.value && availableSlot.value.controllerCount !== undefined) {
    return availableSlot.value.controllerCount > 0
  }
  
  // 使用异步计算的结果
  if (!form.startDate || !form.endDate) return availableControllers.value.length > 0
  
  return controllerAvailabilityState.value.hasAvailable
})

const availableControllersCount = computed(() => {
  if (!availableControllers.value.length) return 0
  
  // 如果有查找到的档期信息，优先使用它的手柄信息
  if (availableSlot.value && availableSlot.value.controllerCount !== undefined) {
    return availableSlot.value.controllerCount
  }
  
  if (!form.startDate || !form.endDate) return availableControllers.value.length
  
  // 使用异步计算的结果
  return controllerAvailabilityState.value.count
})

// 异步检查手柄可用性
const checkControllerAvailability = async () => {
  if (!form.startDate || !form.endDate || !availableControllers.value.length) {
    controllerAvailabilityState.value = {
      checked: true,
      hasAvailable: availableControllers.value.length > 0,
      count: availableControllers.value.length,
      availableControllers: availableControllers.value
    }
    return
  }
  
  try {
    // 批量检查所有手柄的可用性
    const availabilityResults = await checkAccessoriesAvailability(availableControllers.value)
    const availableControllersList = availableControllers.value.filter((_, index) => availabilityResults[index])
    
    controllerAvailabilityState.value = {
      checked: true,
      hasAvailable: availableControllersList.length > 0,
      count: availableControllersList.length,
      availableControllers: availableControllersList
    }
  } catch (error) {
    console.error('检查手柄可用性失败:', error)
    controllerAvailabilityState.value = {
      checked: true,
      hasAvailable: false,
      count: 0,
      availableControllers: []
    }
  }
}

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
    { pattern: /^1[3-9]\d{9}$/, message: '请输入正确的手机号码', trigger: 'blur' }
  ],
  destination: [
    // 收件信息改为非必填
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
  // 重置可用档期和手柄状态
  availableSlot.value = null
  controllerAvailabilityState.value.checked = false
  // 异步检查手柄可用性
  nextTick(() => {
    checkControllerAvailability()
  })
}

const handleEndDateChange = (date: Date | null) => {
  form.endDate = date
  // 重置可用档期和手柄状态
  availableSlot.value = null
  controllerAvailabilityState.value.checked = false
  // 异步检查手柄可用性
  nextTick(() => {
    checkControllerAvailability()
  })
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
  if (value && value.trim()) {
    const phoneMatch = value.match(/1[3-9]\d{9}/)
    if (phoneMatch && !form.customerPhone) {
      form.customerPhone = phoneMatch[0]
      ElMessage.success(`已自动提取手机号: ${phoneMatch[0]}`)
    }
  }
}

const findAvailableAccessory = async () => {
  if (!canSearchSlot.value) {
    ElMessage.warning('请先完善日期和物流信息')
    return
  }

  searchingAccessory.value = true
  try {
    // 使用统一的find-slot接口查找手柄附件
    const result = await ganttStore.findAvailableSlot(
      formatDateToString(form.startDate),
      formatDateToString(form.endDate),
      form.logisticsDays,
      '%controller%'  // 查找包含controller的设备型号
    )

    if (!result.device) {
      throw new Error('在指定时间段内没有可用的手柄附件')
    }

    // 设置查找到的附件信息
    availableAccessorySlot.value = {
      accessory: result.device,
      shipOutDate: result.shipOutDate,
      shipInDate: result.shipInDate
    }

    // 不再自动设置，而是等用户点击添加按钮
    
    ElMessage.success(`找到可用附件: ${result.device.name}`)
  } catch (error) {
    console.error('查找附件失败:', error)
    ElMessage.error((error as Error).message)
    availableAccessorySlot.value = null
  } finally {
    searchingAccessory.value = false
  }
}

// 添加找到的附件到选择列表
const addFoundAccessory = () => {
  if (availableAccessorySlot.value?.accessory) {
    const accessoryId = availableAccessorySlot.value.accessory.id
    if (!form.selectedAccessoryIds.includes(accessoryId)) {
      form.selectedAccessoryIds.push(accessoryId)
      ElMessage.success(`已添加附件: ${availableAccessorySlot.value.accessory.name}`)
    } else {
      ElMessage.warning('该附件已经添加过了')
    }
    availableAccessorySlot.value = null
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
      
      // 使用选定设备的型号
      const deviceModel = selectedDevice.device_model?.display_name || selectedDevice.model || props.selectedDeviceModel || 'x200u'
      result = await ganttStore.findAvailableSlot(
        formatDateToString(form.startDate),
        formatDateToString(form.endDate),
        form.logisticsDays,
        deviceModel
      )
      
      // 验证返回的设备是否是指定设备
      if (result.device.id !== form.selectedDeviceId) {
        throw new Error(`指定设备 ${selectedDevice.name} 在该时间段不可用`)
      }
    } else {
      // 未指定设备，使用甘特图选中的型号自动查找可用设备
      const deviceModel = props.selectedDeviceModel || 'x200u'
      result = await ganttStore.findAvailableSlot(
        formatDateToString(form.startDate),
        formatDateToString(form.endDate),
        form.logisticsDays,
        deviceModel
      )
      
      // 自动填入找到的设备
      form.selectedDeviceId = result.device.id
    }
    
    availableSlot.value = {
      device: result.device,
      shipOutDate: result.shipOutDate,
      shipInDate: result.shipInDate,
      availableControllers: result.availableControllers,
      controllerCount: result.controllerCount
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
    // 首先检查重复租赁
    const duplicateCheck = await checkDuplicateRental()
    if (duplicateCheck.hasDuplicate) {
      const shouldContinue = await handleDuplicateConfirmation(duplicateCheck.duplicates)
      if (!shouldContinue) {
        return
      }
    }

    const startDate = dayjs(form.startDate!)
    const endDate = dayjs(form.endDate!)
    const shipOutTime = toAPIFormat(startDate.subtract(form.logisticsDays, 'day').subtract(1, 'day').hour(9).minute(0).second(0))
    const shipInTime = toAPIFormat(endDate.add(form.logisticsDays, 'day').add(1, 'day').hour(18).minute(0).second(0))

    // 如果选择了附件，添加到租赁配件列表
    let selectedAccessories: number[] = []
    if (form.selectedAccessoryIds.length > 0) {
      selectedAccessories = [...form.selectedAccessoryIds]
    } else if (form.needController) {
      // 兼容旧的手柄逻辑，自动选择一个可用的手柄
      let availableController = null

      // 如果有查找档期的结果，优先从其可用手柄中选择
      if (availableSlot.value && availableSlot.value.availableControllers && availableSlot.value.availableControllers.length > 0) {
        const controllerId = availableSlot.value.availableControllers[0]
        availableController = availableControllers.value.find(c => c.id === controllerId)
      } else {
        // 否则使用异步检查的结果选择可用手柄
        if (controllerAvailabilityState.value.availableControllers.length > 0) {
          availableController = controllerAvailabilityState.value.availableControllers[0]
        }
      }

      if (availableController) {
        selectedAccessories = [availableController.id]
      } else {
        ElMessage.warning('当前档期没有可用手柄，将不包含手柄')
      }
    }

    const rentalData = {
      device_id: deviceId!,
      start_date: formatDateToString(form.startDate),
      end_date: formatDateToString(form.endDate),
      customer_name: form.customerName,
      customer_phone: form.customerPhone || '',
      destination: form.destination || '',
      ship_out_time: shipOutTime,
      ship_in_time: shipInTime,
      accessories: selectedAccessories
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

// 检查重复租赁
const checkDuplicateRental = async () => {
  try {
    const response = await axios.post('/api/rentals/check-duplicate', {
      customer_name: form.customerName,
      destination: form.destination
    })

    if (response.data.success) {
      return {
        hasDuplicate: response.data.has_duplicate,
        duplicates: response.data.duplicates || []
      }
    } else {
      console.error('检查重复租赁失败:', response.data.error)
      return { hasDuplicate: false, duplicates: [] }
    }
  } catch (error) {
    console.error('检查重复租赁失败:', error)
    return { hasDuplicate: false, duplicates: [] }
  }
}

// 处理重复租赁确认
const handleDuplicateConfirmation = async (duplicates: any[]) => {
  try {
    // 构建重复信息显示
    let duplicateInfo = '检测到可能重复的租赁记录：\n\n'

    duplicates.forEach((duplicate, index) => {
      duplicateInfo += `${index + 1}. 设备：${duplicate.device_name}\n`
      duplicateInfo += `   客户：${duplicate.customer_name}\n`
      duplicateInfo += `   地址：${duplicate.destination}\n`
      duplicateInfo += `   时间：${duplicate.start_date} 至 ${duplicate.end_date}\n`
      duplicateInfo += `   状态：${duplicate.status}\n`
      duplicateInfo += `   重复原因：${duplicate.duplicate_reasons.join(', ')}\n\n`
    })

    duplicateInfo += '是否仍要继续创建新的租赁记录？'

    await ElMessageBox.confirm(
      duplicateInfo,
      '重复租赁提醒',
      {
        type: 'warning',
        confirmButtonText: '继续创建',
        cancelButtonText: '取消',
        dangerouslyUseHTMLString: false
      }
    )

    return true // 用户确认继续
  } catch {
    return false // 用户取消
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

  // 如果选择了附件，添加到租赁配件列表
  let selectedAccessories: number[] = []
  if (form.selectedAccessoryIds.length > 0) {
    selectedAccessories = [...form.selectedAccessoryIds]
  } else if (form.needController) {
    // 兼容旧的手柄逻辑，自动选择一个可用的手柄
    let availableController = null
    
    // 如果有查找档期的结果，优先从其可用手柄中选择
    if (availableSlot.value && availableSlot.value.availableControllers && availableSlot.value.availableControllers.length > 0) {
      const controllerId = availableSlot.value.availableControllers[0]
      availableController = availableControllers.value.find(c => c.id === controllerId)
    } else {
      // 否则使用异步检查的结果选择可用手柄
      if (controllerAvailabilityState.value.availableControllers.length > 0) {
        availableController = controllerAvailabilityState.value.availableControllers[0]
      }
    }
    
    if (availableController) {
      selectedAccessories = [availableController.id]
    }
  }

  const rentalData = {
    device_id: deviceId,
    start_date: formatDateToString(form.startDate),
    end_date: formatDateToString(form.endDate),
    customer_name: form.customerName,
    customer_phone: form.customerPhone || '',
    destination: form.destination || '',
    ship_out_time: shipOutTime,
    ship_in_time: shipInTime,
    accessories: selectedAccessories,
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
  availableAccessorySlot.value = null
  searching.value = false
  searchingAccessory.value = false
  submitting.value = false
  
  // 重置表单数据
  Object.assign(form, {
    startDate: null,
    endDate: null,
    logisticsDays: 1,
    selectedDeviceId: null,
    customerName: '',
    customerPhone: '',
    destination: '',
    selectedAccessoryIds: [],
    needController: false
  })
  
  emit('update:modelValue', false)
}

const formatDateTime = (date: Date) => {
  return dayjs(date).format('YYYY-MM-DD HH:mm')
}

// 检查附件是否可用（新架构：需要通过API检查所有租赁记录）
const isAccessoryAvailable = async (accessory: any) => {
  if (!form.startDate || !form.endDate) return true
  
  try {
    // 使用API检查设备可用性
    const response = await axios.post('/api/rentals/check-conflict', {
      device_id: accessory.id,
      start_date: form.startDate,
      end_date: form.endDate
    })
    
    return response.data.success && !response.data.has_conflict
  } catch (error) {
    console.error('检查附件可用性失败:', error)
    // 发生错误时保守处理，认为不可用
    return false
  }
}

// 批量检查多个附件的可用性
const checkAccessoriesAvailability = async (accessories: any[]) => {
  if (!form.startDate || !form.endDate) return accessories.map(() => true)
  
  try {
    const checks = accessories.map(accessory => 
      axios.post('/api/rentals/check-conflict', {
        device_id: accessory.id,
        start_date: form.startDate,
        end_date: form.endDate
      })
    )
    
    const results = await Promise.all(checks)
    return results.map((response: any) => 
      response.data.success && !response.data.has_conflict
    )
  } catch (error) {
    console.error('批量检查附件可用性失败:', error)
    // 发生错误时保守处理，都认为不可用
    return accessories.map(() => false)
  }
}

// 监听对话框打开和日期变化，自动检查手柄可用性
watch([() => props.modelValue, () => form.startDate, () => form.endDate], async ([visible, startDate, endDate]) => {
  if (visible) {
    // 对话框打开时，先加载附件列表
    await loadAvailableControllers()
    
    if (startDate && endDate) {
      // 对话框打开且有日期时，检查手柄可用性
      nextTick(() => {
        checkControllerAvailability()
      })
    } else {
      // 对话框打开但没有日期时，重置状态
      controllerAvailabilityState.value = {
        checked: true,
        hasAvailable: availableControllers.value.length > 0,
        count: availableControllers.value.length,
        availableControllers: availableControllers.value
      }
    }
  }
}, { immediate: true })

// 注意：新架构中手柄可用性检查现在通过API异步进行
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

.controller-section {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 4px;
  padding: 12px;
  background-color: var(--el-fill-color-lighter);
}

.controller-available {
  color: var(--el-color-success);
  font-size: 12px;
  margin-left: 8px;
}

.controller-unavailable {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 8px;
  color: var(--el-color-error);
  font-size: 12px;
}
</style>

