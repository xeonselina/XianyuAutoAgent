<template>
  <el-dialog
    v-model="dialogVisible"
    title="编辑租赁记录"
    width="500px"
    :close-on-click-modal="false"
    @close="handleClose"
  >
    <RentalActionButtons
      :rental="rental"
      :loading-latest-data="loadingLatestData"
      :latest-data-error="latestDataError"
      :submitting="submitting"
      @open-contract="openContract"
      @open-shipping-order="openShippingOrder"
      @delete="handleDelete"
      @close="handleClose"
      @submit="handleSubmit"
    />

    <el-form
      ref="formRef"
      :model="form"
      :rules="rules"
      label-width="120px"
      v-if="rental"
    >
      <!-- 基础信息表单 -->
      <RentalBasicForm
        :form="form"
        :rental="rental"
        :available-devices="deviceManagement.devices.value"
        :loading-devices="deviceManagement.loading.value"
        :min-selectable-date="minSelectableDate"
        @device-change="handleDeviceChange"
        @end-date-change="handleEndDateChange"
        @device-selector-focus="handleDeviceSelectorFocus"
      />

      <!-- 物流信息表单 -->
      <RentalShippingForm
        :form="form"
        :querying-ship-out="queryingShipOut"
        :querying-ship-in="queryingShipIn"
        @query-ship-out="queryShipOutTracking"
        @query-ship-in="queryShipInTracking"
        @ship-out-time-change="handleShipOutTimeChange"
        @ship-in-time-change="handleShipInTimeChange"
        @status-change="handleStatusChange"
      />

      <!-- 附件选择 -->
      <RentalAccessorySelector
        :form="form"
        :rental="rental"
        :available-controllers="deviceManagement.accessories.value"
        :loading-accessories="deviceManagement.loading.value"
        :searching-accessory="searchingAccessory"
        @find-accessory="findAvailableAccessory"
        @remove-accessory="removeController"
        @accessory-change="handleAccessoryChange"
        @accessory-selector-focus="handleAccessorySelectorFocus"
      />
    </el-form>

    <template #footer>
      <div class="dialog-footer">
        <el-button @click="handleClose">取消</el-button>
        <el-button
          type="primary"
          @click="handleSubmit"
          :loading="submitting"
        >
          保存
        </el-button>
      </div>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { ElMessage, ElMessageBox, type FormInstance } from 'element-plus'
import { useRouter } from 'vue-router'
import dayjs from 'dayjs'

// Store & Composables
import { useGanttStore } from '@/stores/gantt'
import type { Rental } from '@/stores/gantt'
import { useDeviceManagement } from '@/composables/useDeviceManagement'
import { useAvailabilityCheck } from '@/composables/useAvailabilityCheck'
import { useConflictDetection } from '@/composables/useConflictDetection'
import { getEditRentalRules } from '@/composables/useRentalFormValidation'

// Components
import RentalActionButtons from './RentalActionButtons.vue'
import RentalBasicForm from './RentalBasicForm.vue'
import RentalShippingForm from './RentalShippingForm.vue'
import RentalAccessorySelector from './RentalAccessorySelector.vue'

// Props & Emits
interface Props {
  modelValue: boolean
  rental: Rental | null
}

const props = defineProps<Props>()
const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  'success': []
}>()

// Store & Router
const ganttStore = useGanttStore()
const router = useRouter()

// Composables
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
  deviceId: 0,
  endDate: null as Date | null,
  customerPhone: '',
  destination: '',
  shipOutTrackingNo: '',
  shipInTrackingNo: '',
  shipOutTime: null as Date | null,
  shipInTime: null as Date | null,
  status: 'not_shipped',
  accessories: [] as number[]
})

// UI State
const submitting = ref(false)
const loadingLatestData = ref(false)
const latestDataError = ref<string | null>(null)
const searchingAccessory = ref(false)
const queryingShipOut = ref(false)
const queryingShipIn = ref(false)
const deviceConflictChecked = ref(false)
const accessoryConflictChecked = ref(false)

// Form Rules
const rules = getEditRentalRules()

// Computed
const minSelectableDate = computed(() => {
  if (!props.rental) return null
  return new Date(props.rental.start_date)
})

// Handlers
const handleClose = () => {
  dialogVisible.value = false
}

const handleDelete = async () => {
  if (!props.rental) return

  try {
    await ElMessageBox.confirm(
      '确定要删除这条租赁记录吗？此操作不可撤销。',
      '删除确认',
      {
        confirmButtonText: '确定删除',
        cancelButtonText: '取消',
        type: 'warning'
      }
    )

    submitting.value = true
    await ganttStore.deleteRental(props.rental.id)
    ElMessage.success('租赁记录删除成功')
    emit('success')
    handleClose()
  } catch (error: any) {
    if (error !== 'cancel') {
      ElMessage.error('删除失败：' + (error.message || '未知错误'))
    }
  } finally {
    submitting.value = false
  }
}

const handleSubmit = async () => {
  try {
    await formRef.value?.validate()
    submitting.value = true

    const updateData = {
      device_id: form.value.deviceId,
      end_date: dayjs(form.value.endDate).format('YYYY-MM-DD'),
      customer_phone: form.value.customerPhone,
      destination: form.value.destination,
      ship_out_tracking_no: form.value.shipOutTrackingNo,
      ship_in_tracking_no: form.value.shipInTrackingNo,
      ship_out_time: form.value.shipOutTime
        ? dayjs(form.value.shipOutTime).format('YYYY-MM-DD HH:mm:ss')
        : null,
      ship_in_time: form.value.shipInTime
        ? dayjs(form.value.shipInTime).format('YYYY-MM-DD HH:mm:ss')
        : null,
      status: form.value.status,
      accessories: form.value.accessories
    }

    await ganttStore.updateRental(props.rental!.id, updateData)
    ElMessage.success('租赁记录更新成功')
    emit('success')
    handleClose()
  } catch (error: any) {
    ElMessage.error('更新失败：' + (error.message || '未知错误'))
  } finally {
    submitting.value = false
  }
}

const handleEndDateChange = (date: Date) => {
  console.log('End date changed:', date)
}

const handleDeviceSelectorFocus = async () => {
  if (!deviceConflictChecked.value && props.rental) {
    await checkDevicesConflict()
    deviceConflictChecked.value = true
  }
}

const handleDeviceChange = async (deviceId: number) => {
  if (!props.rental) return

  const selectedDevice = deviceManagement.devices.value.find(d => d.id === deviceId)
  if (!selectedDevice) return

  try {
    const shipOutTime = props.rental.ship_out_time || props.rental.start_date
    const shipInTime = props.rental.ship_in_time || props.rental.end_date

    const hasConflict = await conflictDetection.checkDeviceConflict({
      deviceId,
      startDate: shipOutTime,
      endDate: shipInTime,
      excludeRentalId: props.rental.id
    })

    if (hasConflict) {
      ElMessageBox.confirm(
        `设备 "${selectedDevice.name}" 在该时间段有冲突，确定要选择吗？`,
        '设备冲突警告',
        {
          confirmButtonText: '确定选择',
          cancelButtonText: '取消',
          type: 'warning'
        }
      ).catch(() => {
        if (props.rental) {
          form.value.deviceId = props.rental.device_id
        }
      })
    }
  } catch (error) {
    console.error('检查设备冲突失败:', error)
  }
}

const handleShipOutTimeChange = (time: Date) => {
  console.log('Ship out time changed:', time)
}

const handleShipInTimeChange = (time: Date) => {
  console.log('Ship in time changed:', time)
}

const handleStatusChange = (status: string) => {
  console.log('Status changed:', status)
}

const queryShipOutTracking = () => {
  console.log('Query ship out tracking')
}

const queryShipInTracking = () => {
  console.log('Query ship in tracking')
}

const findAvailableAccessory = async () => {
  if (!props.rental) return

  searchingAccessory.value = true
  try {
    let logisticsDays = 1
    if (props.rental.start_date && props.rental.ship_out_time) {
      const startDate = new Date(props.rental.start_date)
      const shipOutTime = new Date(props.rental.ship_out_time)
      const diffTime = startDate.getTime() - shipOutTime.getTime()
      logisticsDays = Math.max(1, Math.ceil(diffTime / (1000 * 60 * 60 * 24)) - 1)
    }

    const slotResponse = await ganttStore.findAvailableSlot(
      props.rental.start_date,
      props.rental.end_date,
      logisticsDays,
      1, // X200U 型号 ID
      true // is_accessory
    )

    // 更新所有附件的可用性状态
    const availableDeviceIds = slotResponse.availableDevices || []
    deviceManagement.accessories.value.forEach(accessory => {
      if (accessory.model && accessory.model.includes('手柄')) {
        accessory.isAvailable = availableDeviceIds.includes(accessory.id)
        accessory.conflictReason = accessory.isAvailable ? undefined : '档期冲突'
      }
    })

    ElMessage.success('手柄档期检查完成')
  } catch (error) {
    console.error('检查手柄档期失败:', error)
    ElMessage.error('检查手柄档期失败')
  } finally {
    searchingAccessory.value = false
  }
}

const removeController = (controllerId: number) => {
  form.value.accessories = form.value.accessories.filter(id => id !== controllerId)
}

const handleAccessorySelectorFocus = async () => {
  if (!accessoryConflictChecked.value) {
    await findAvailableAccessory()
    accessoryConflictChecked.value = true
  }
}

const handleAccessoryChange = async (accessoryIds: number[]) => {
  const newAccessoryIds = accessoryIds.filter(id => !form.value.accessories.includes(id))

  for (const accessoryId of newAccessoryIds) {
    const accessory = deviceManagement.accessories.value.find(a => a.id === accessoryId)
    if (accessory && accessory.isAvailable === false) {
      ElMessageBox.confirm(
        `附件 "${accessory.name}" 在该时间段有冲突，确定要选择吗？`,
        '附件冲突警告',
        {
          confirmButtonText: '确定选择',
          cancelButtonText: '取消',
          type: 'warning'
        }
      ).catch(() => {
        form.value.accessories = form.value.accessories.filter(id => id !== accessoryId)
      })
    }
  }
}

const openContract = () => {
  if (props.rental) {
    const url = router.resolve({ path: `/contract/${props.rental.id}` })
    window.open(url.href, '_blank')
  }
}

const openShippingOrder = () => {
  if (props.rental) {
    const url = router.resolve({ path: `/shipping/${props.rental.id}` })
    window.open(url.href, '_blank')
  }
}

// Check devices conflict
const checkDevicesConflict = async () => {
  if (!props.rental) return

  const shipOutTime = props.rental.ship_out_time || props.rental.start_date
  const shipInTime = props.rental.ship_in_time || props.rental.end_date

  await availability.checkDevicesAvailability(
    deviceManagement.devices.value,
    {
      startDate: shipOutTime,
      endDate: shipInTime,
      excludeRentalId: props.rental.id
    }
  )
}

// Load latest rental data
const loadLatestRentalData = async () => {
  if (!props.rental) return null

  loadingLatestData.value = true
  latestDataError.value = null

  try {
    return await ganttStore.getRentalById(props.rental.id)
  } catch (error: any) {
    console.error('获取最新租赁数据失败:', error)
    latestDataError.value = error.message || '获取最新数据失败'
    return props.rental
  } finally {
    loadingLatestData.value = false
  }
}

// Initialize form
const initForm = async () => {
  if (props.rental) {
    deviceConflictChecked.value = false
    accessoryConflictChecked.value = false

    const latestRental = await loadLatestRentalData()
    const rentalData = latestRental || props.rental

    form.value = {
      deviceId: rentalData.device_id,
      endDate: new Date(rentalData.end_date),
      customerPhone: rentalData.customer_phone || '',
      destination: rentalData.destination || '',
      shipOutTrackingNo: rentalData.ship_out_tracking_no || '',
      shipInTrackingNo: rentalData.ship_in_tracking_no || '',
      shipOutTime: rentalData.ship_out_time ? new Date(rentalData.ship_out_time) : null,
      shipInTime: rentalData.ship_in_time ? new Date(rentalData.ship_in_time) : null,
      status: rentalData.status || 'not_shipped',
      accessories: (rentalData.child_rentals || [])
        .map((child: any) => child.device_id)
        .filter(Boolean)
    }

    if (latestRental) {
      Object.assign(props.rental, latestRental)
    }

    await Promise.all([
      deviceManagement.loadDevices(),
      deviceManagement.loadAccessories()
    ])
  }
}

// Watchers
watch(
  () => props.rental,
  () => {
    if (props.rental) {
      initForm()
    }
  },
  { immediate: true }
)

watch(
  () => props.modelValue,
  (newValue) => {
    if (newValue && props.rental) {
      initForm()
    }
  }
)
</script>

<style scoped>
.dialog-footer {
  text-align: right;
}
</style>
