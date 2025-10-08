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
      <!-- 日期选择 -->
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

      <!-- 设备选择 -->
      <el-form-item label="选择设备" prop="selectedDeviceId">
        <div class="device-selection">
          <el-select
            v-model="form.selectedDeviceId"
            placeholder="请选择设备"
            style="flex: 1"
            clearable
            filterable
            @focus="handleDeviceFocus"
          >
            <el-option
              v-for="device in deviceManagement.devices.value"
              :key="device.id"
              :label="device.name"
              :value="device.id"
            >
              <div class="device-option">
                <span>{{ device.name }}</span>
                <div class="device-status">
                  <span class="device-model">{{ device.model }}</span>
                  <el-tag
                    v-if="availability.deviceAvailability.value.checked && availability.isDeviceAvailable(device.id)"
                    type="success"
                    size="small"
                    effect="dark"
                  >
                    可用
                  </el-tag>
                  <el-tag
                    v-else-if="availability.deviceAvailability.value.checked"
                    type="danger"
                    size="small"
                    effect="dark"
                  >
                    档期不可用
                  </el-tag>
                </div>
              </div>
            </el-option>
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

      <!-- 客户信息 -->
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
          placeholder="请输入收件人信息（姓名、电话、地址）"
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
            @focus="handleAccessoryFocus"
          >
            <el-option
              v-for="accessory in deviceManagement.accessories.value"
              :key="accessory.id"
              :label="accessory.name"
              :value="accessory.id"
            >
              <div class="device-option">
                <span>{{ accessory.name }}</span>
                <div class="device-status">
                  <span class="device-model">{{ accessory.model }}</span>
                  <el-tag
                    v-if="availability.accessoryAvailability.value.checked && availability.isAccessoryAvailable(accessory.id)"
                    type="success"
                    size="small"
                    effect="dark"
                  >
                    可用
                  </el-tag>
                  <el-tag
                    v-else-if="availability.accessoryAvailability.value.checked"
                    type="danger"
                    size="small"
                    effect="dark"
                  >
                    档期不可用
                  </el-tag>
                </div>
              </div>
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
            @click="addFoundAccessory"
            style="margin-top: 8px"
          >
            添加此附件
          </el-button>
        </div>
      </el-form-item>

      <!-- 查找到的档期信息 -->
      <div v-if="availableSlot" class="slot-info">
        <div class="slot-device">
          <el-icon><Monitor /></el-icon>
          已找到可用设备: {{ availableSlot.device?.name || '未知设备' }}
        </div>
        <div class="slot-times">
          <div>寄出时间: {{ formatDateTime(availableSlot.shipOutDate) }}</div>
          <div>收回时间: {{ formatDateTime(availableSlot.shipInDate) }}</div>
        </div>
      </div>
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
import { ref, computed, watch, nextTick } from 'vue'
import { ElMessage, ElMessageBox, type FormInstance } from 'element-plus'
import { Monitor } from '@element-plus/icons-vue'
import VueDatePicker from '@vuepic/vue-datepicker'
import '@vuepic/vue-datepicker/dist/main.css'
import dayjs from 'dayjs'
import axios from 'axios'

// 导入组合式函数
import { useGanttStore } from '@/stores/gantt'
import { useDeviceManagement } from '@/composables/useDeviceManagement'
import { useAvailabilityCheck } from '@/composables/useAvailabilityCheck'
import { useConflictDetection } from '@/composables/useConflictDetection'
import { getCreateRentalRules } from '@/composables/useRentalFormValidation'

// Props & Emits
interface Props {
  modelValue: boolean
  selectedDeviceModel?: string // 当前甘特图选择的设备型号 display_name
}

const props = defineProps<Props>()
const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  'success': []
}>()

// Store & Composables
const ganttStore = useGanttStore()
const deviceManagement = useDeviceManagement()
const availability = useAvailabilityCheck()
const conflictDetection = useConflictDetection()

// Refs
const formRef = ref<FormInstance>()
const dialogVisible = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value)
})

// Form State
const form = ref({
  startDate: null as Date | null,
  endDate: null as Date | null,
  logisticsDays: 1,
  selectedDeviceId: null as number | null,
  customerName: '',
  customerPhone: '',
  destination: '',
  selectedAccessoryIds: [] as number[]
})

// UI State
const submitting = ref(false)
const searching = ref(false)
const searchingAccessory = ref(false)
const availableSlot = ref<any>(null)
const availableAccessorySlot = ref<any>(null)

// Form Rules
const rules = getCreateRentalRules()

// Computed
const canSearchSlot = computed(() => {
  return form.value.startDate && form.value.endDate && form.value.logisticsDays >= 0
})

// Date Methods
const disabledDate = (date: Date) => {
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  return date < today
}

const disabledEndDate = (date: Date) => {
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  if (date < today) return true
  if (form.value.startDate) {
    return dayjs(date).isBefore(dayjs(form.value.startDate), 'day')
  }
  return false
}

const formatDateTime = (date: Date) => {
  return dayjs(date).format('YYYY-MM-DD HH:mm')
}

// Date Change Handlers
const handleStartDateChange = (date: Date | null) => {
  form.value.startDate = date
  if (date && form.value.endDate && dayjs(form.value.endDate).isBefore(dayjs(date))) {
    form.value.endDate = null
  }

  availableSlot.value = null
  availability.resetAll()

  if (date && form.value.endDate) {
    nextTick(() => {
      checkAvailabilities()
    })
  }
}

const handleEndDateChange = (date: Date | null) => {
  form.value.endDate = date
  availableSlot.value = null
  availability.resetAll()

  if (date && form.value.startDate) {
    nextTick(() => {
      checkAvailabilities()
    })
  }
}

// Availability Check
const checkAvailabilities = async () => {
  if (!form.value.startDate || !form.value.endDate) return

  const params = {
    startDate: dayjs(form.value.startDate).format('YYYY-MM-DD'),
    endDate: dayjs(form.value.endDate).format('YYYY-MM-DD'),
    logisticsDays: form.value.logisticsDays
  }

  await Promise.all([
    availability.checkDevicesAvailability(deviceManagement.devices.value, params),
    availability.checkAccessoriesAvailability(deviceManagement.accessories.value, params)
  ])
}

// Device Focus Handler
const handleDeviceFocus = async () => {
  if (!form.value.startDate || !form.value.endDate) {
    ElMessage.warning('请先选择日期后查看设备可用性')
    return
  }

  if (!availability.deviceAvailability.value.checked) {
    await checkAvailabilities()
  }
}

// Accessory Focus Handler
const handleAccessoryFocus = async () => {
  if (!form.value.startDate || !form.value.endDate) {
    ElMessage.warning('请先选择日期后查看附件可用性')
    return
  }

  if (!availability.accessoryAvailability.value.checked) {
    await checkAvailabilities()
  }
}

// Find Available Slot
const findAvailableSlot = async () => {
  if (!canSearchSlot.value) {
    ElMessage.warning('请先完善日期和物流信息')
    return
  }

  // 获取当前选择的设备型号的 model_id
  let modelId = ''
  if (props.selectedDeviceModel) {
    const selectedModel = deviceManagement.deviceModels.value.find(
      (m: any) => m.display_name === props.selectedDeviceModel
    )
    if (selectedModel) {
      modelId = selectedModel.id.toString()
    }
  }

  if (!modelId) {
    ElMessage.warning('请先在甘特图中选择设备型号筛选')
    return
  }

  searching.value = true
  try {
    const result = await ganttStore.findAvailableSlot(
      dayjs(form.value.startDate).format('YYYY-MM-DD'),
      dayjs(form.value.endDate).format('YYYY-MM-DD'),
      form.value.logisticsDays,
      modelId, // 使用当前甘特图选择的型号
      false
    )

    if (result.device) {
      availableSlot.value = result
      form.value.selectedDeviceId = result.device.id
      ElMessage.success(`找到可用设备: ${result.device.name}`)
    } else {
      throw new Error('在指定时间段内没有可用设备')
    }
  } catch (error) {
    console.error('查找档期失败:', error)
    ElMessage.error((error as Error).message)
    availableSlot.value = null
  } finally {
    searching.value = false
  }
}

// Find Available Accessory
const findAvailableAccessory = async () => {
  if (!canSearchSlot.value) {
    ElMessage.warning('请先完善日期和物流信息')
    return
  }

  // 查找所有可用附件（暂时不限制附件型号）
  // TODO: 后续可以根据主设备型号的关联附件来筛选
  const accessoryModelId = ''

  searchingAccessory.value = true
  try {
    const result = await ganttStore.findAvailableSlot(
      dayjs(form.value.startDate).format('YYYY-MM-DD'),
      dayjs(form.value.endDate).format('YYYY-MM-DD'),
      form.value.logisticsDays,
      accessoryModelId, // 查找所有附件
      true
    )

    if (result.device) {
      availableAccessorySlot.value = {
        accessory: result.device,
        shipOutDate: result.shipOutDate,
        shipInDate: result.shipInDate
      }
      ElMessage.success(`找到可用附件: ${result.device.name}`)
    } else {
      throw new Error('在指定时间段内没有可用的附件')
    }
  } catch (error) {
    console.error('查找附件失败:', error)
    ElMessage.error((error as Error).message)
    availableAccessorySlot.value = null
  } finally {
    searchingAccessory.value = false
  }
}

// Add Found Accessory
const addFoundAccessory = () => {
  if (availableAccessorySlot.value?.accessory) {
    const accessoryId = availableAccessorySlot.value.accessory.id
    if (!form.value.selectedAccessoryIds.includes(accessoryId)) {
      form.value.selectedAccessoryIds.push(accessoryId)
      ElMessage.success(`已添加附件: ${availableAccessorySlot.value.accessory.name}`)
    } else {
      ElMessage.warning('该附件已经添加过了')
    }
    availableAccessorySlot.value = null
  }
}

// Submit Handler
const handleSubmit = async () => {
  try {
    await formRef.value?.validate()
  } catch {
    return
  }

  // 检查重复租赁
  const duplicateCheck = await conflictDetection.checkDuplicateRental({
    customerName: form.value.customerName,
    destination: form.value.destination
  })

  if (duplicateCheck.hasDuplicate) {
    try {
      let duplicateInfo = '检测到可能重复的租赁记录：\n\n'
      duplicateCheck.duplicates.forEach((duplicate: any, index: number) => {
        duplicateInfo += `${index + 1}. 设备：${duplicate.device_name}\n`
        duplicateInfo += `   客户：${duplicate.customer_name}\n`
        duplicateInfo += `   地址：${duplicate.destination}\n`
        duplicateInfo += `   时间：${duplicate.start_date} 至 ${duplicate.end_date}\n`
        duplicateInfo += `   状态：${duplicate.status}\n\n`
      })
      duplicateInfo += '是否仍要继续创建新的租赁记录？'

      await ElMessageBox.confirm(
        duplicateInfo,
        '重复租赁提醒',
        {
          type: 'warning',
          confirmButtonText: '继续创建',
          cancelButtonText: '取消'
        }
      )
    } catch {
      return
    }
  }

  submitting.value = true
  try {
    const deviceId = form.value.selectedDeviceId || availableSlot.value?.device.id
    if (!deviceId) {
      ElMessage.error('请选择设备')
      return
    }

    const shipOutTime = availableSlot.value
      ? availableSlot.value.shipOutDate
      : dayjs(form.value.startDate).subtract(form.value.logisticsDays, 'day').toDate()
    const shipInTime = availableSlot.value
      ? availableSlot.value.shipInDate
      : dayjs(form.value.endDate).add(form.value.logisticsDays, 'day').toDate()

    const rentalData = {
      device_id: deviceId,
      start_date: dayjs(form.value.startDate).format('YYYY-MM-DD'),
      end_date: dayjs(form.value.endDate).format('YYYY-MM-DD'),
      customer_name: form.value.customerName,
      customer_phone: form.value.customerPhone,
      destination: form.value.destination,
      ship_out_time: dayjs(shipOutTime).format('YYYY-MM-DD HH:mm:ss'),
      ship_in_time: dayjs(shipInTime).format('YYYY-MM-DD HH:mm:ss'),
      accessories: form.value.selectedAccessoryIds
    }

    await ganttStore.createRental(rentalData)
    ElMessage.success('租赁记录创建成功')
    emit('success')
    handleClose()
  } catch (error: any) {
    ElMessage.error('创建失败：' + (error.message || '未知错误'))
  } finally {
    submitting.value = false
  }
}

// Close Handler
const handleClose = () => {
  formRef.value?.resetFields()
  form.value = {
    startDate: null,
    endDate: null,
    logisticsDays: 1,
    selectedDeviceId: null,
    customerName: '',
    customerPhone: '',
    destination: '',
    selectedAccessoryIds: []
  }
  availableSlot.value = null
  availableAccessorySlot.value = null
  availability.resetAll()
  emit('update:modelValue', false)
}

// Watch Dialog Open
watch(() => props.modelValue, async (visible) => {
  if (visible) {
    await Promise.all([
      deviceManagement.loadDevices(),
      deviceManagement.loadAccessories(),
      deviceManagement.loadDeviceModels()
    ])
  }
}, { immediate: true })
</script>

<style scoped>
.device-selection {
  display: flex;
  align-items: center;
  width: 100%;
}

.device-option {
  display: flex;
  justify-content: space-between;
  align-items: center;
  width: 100%;
}

.device-status {
  display: flex;
  align-items: center;
  gap: 8px;
}

.device-model {
  color: var(--el-text-color-secondary);
  font-size: 13px;
}

.form-tip {
  font-size: 12px;
  color: var(--el-text-color-placeholder);
  margin-top: 4px;
}

.slot-info {
  padding: 12px;
  background: var(--el-color-success-light-9);
  border-radius: 4px;
  margin-top: 12px;
}

.slot-device {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
  color: var(--el-color-success);
  margin-bottom: 8px;
}

.slot-times {
  font-size: 14px;
  color: var(--el-text-color-regular);
}

.dialog-footer {
  text-align: right;
}
</style>
