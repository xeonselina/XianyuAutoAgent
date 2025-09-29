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
        :available-devices="availableDevices"
        :loading-devices="loadingDevices"
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
        :available-controllers="availableControllers"
        :loading-accessories="loadingAccessories"
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
import { ref, computed, watch, onMounted } from 'vue'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import { useRouter } from 'vue-router'
import { useGanttStore } from '@/stores/gantt'
import type { Device, Rental } from '@/stores/gantt'
import axios from 'axios'
import dayjs from 'dayjs'

// 导入子组件
import RentalActionButtons from './RentalActionButtons.vue'
import RentalBasicForm from './RentalBasicForm.vue'
import RentalShippingForm from './RentalShippingForm.vue'
import RentalAccessorySelector from './RentalAccessorySelector.vue'

interface Props {
  modelValue: boolean
  rental: Rental | null
}

interface AccessoryWithStatus extends Device {
  isAvailable?: boolean
  conflictReason?: string
}

interface DeviceWithConflictStatus extends Device {
  conflicted?: boolean
}

const props = defineProps<Props>()
const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  'success': []
}>()

// Store and Router
const ganttStore = useGanttStore()
const router = useRouter()

// Refs
const formRef = ref<FormInstance>()
const dialogVisible = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value)
})

// 表单数据
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

// 状态管理
const submitting = ref(false)
const loadingLatestData = ref(false)
const latestDataError = ref<string | null>(null)
const loadingDevices = ref(false)
const loadingAccessories = ref(false)
const searchingAccessory = ref(false)
const queryingShipOut = ref(false)
const queryingShipIn = ref(false)
const deviceConflictChecked = ref(false) // 标记是否已检查设备冲突
const accessoryConflictChecked = ref(false) // 标记是否已检查附件冲突

// 数据
const availableDevices = ref<DeviceWithConflictStatus[]>([])
const availableControllers = ref<AccessoryWithStatus[]>([])

// 计算属性
const minSelectableDate = computed(() => {
  if (!props.rental) return null
  return new Date(props.rental.start_date)
})

// 表单验证规则
const rules: FormRules = {
  deviceId: [
    { required: true, message: '请选择设备', trigger: 'change' }
  ],
  endDate: [
    { required: true, message: '请选择结束日期', trigger: 'change' }
  ],
  customerPhone: [
    { pattern: /^1[3-9]\d{9}$/, message: '请输入正确的手机号码', trigger: 'blur' }
  ]
}

// 方法
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
        type: 'warning',
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

    // 构建更新数据
    const updateData = {
      device_id: form.value.deviceId,
      end_date: dayjs(form.value.endDate).format('YYYY-MM-DD'),
      customer_phone: form.value.customerPhone,
      destination: form.value.destination,
      ship_out_tracking_no: form.value.shipOutTrackingNo,
      ship_in_tracking_no: form.value.shipInTrackingNo,
      ship_out_time: form.value.shipOutTime ? dayjs(form.value.shipOutTime).format('YYYY-MM-DD HH:mm:ss') : null,
      ship_in_time: form.value.shipInTime ? dayjs(form.value.shipInTime).format('YYYY-MM-DD HH:mm:ss') : null,
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
  // 结束日期变更逻辑
  console.log('End date changed:', date)
}

const handleDeviceSelectorFocus = async () => {
  // 只在首次点击时检查设备冲突
  if (!deviceConflictChecked.value) {
    await checkDevicesConflictOnDemand()
    deviceConflictChecked.value = true
  }
}

const handleDeviceChange = async (deviceId: number) => {
  // 设备变更时检查新设备的冲突状态
  console.log('Device change detected:', deviceId)
  if (props.rental) {
    const selectedDevice = availableDevices.value.find(device => device.id === deviceId)
    if (selectedDevice) {
      try {
        // 使用租赁的实际寄出和收回时间进行冲突检查
        const shipOutTime = props.rental.ship_out_time || props.rental.start_date
        const shipInTime = props.rental.ship_in_time || props.rental.end_date

        const hasConflict = await checkDeviceConflict(
          deviceId,
          shipOutTime,
          shipInTime,
          props.rental.id
        )

        if (hasConflict) {
          ElMessageBox.confirm(
            `设备 "${selectedDevice.name}" 在该时间段有冲突，确定要选择吗？`,
            '设备冲突警告',
            {
              confirmButtonText: '确定选择',
              cancelButtonText: '取消',
              type: 'warning',
            }
          ).catch(() => {
            // 用户取消，恢复原设备
            if (props.rental) {
              form.value.deviceId = props.rental.device_id
            }
          })
        }
      } catch (error) {
        console.error('检查设备冲突失败:', error)
      }
    }
  }
}

const handleShipOutTimeChange = (time: Date) => {
  // 寄出时间变更逻辑
  console.log('Ship out time changed:', time)
}

const handleShipInTimeChange = (time: Date) => {
  // 收回时间变更逻辑
  console.log('Ship in time changed:', time)
}

const handleStatusChange = (status: string) => {
  // 状态变更逻辑
  console.log('Status changed:', status)
}

const queryShipOutTracking = () => {
  // 查询寄出物流
  console.log('Query ship out tracking')
}

const queryShipInTracking = () => {
  // 查询寄回物流
  console.log('Query ship in tracking')
}

const findAvailableAccessory = async () => {
  // 使用一次 find-slot 请求检查手柄档期
  if (!props.rental) return

  searchingAccessory.value = true
  try {
    // 计算物流天数
    let logisticsDays = 1
    if (props.rental.start_date && props.rental.ship_out_time) {
      const startDate = new Date(props.rental.start_date)
      const shipOutTime = new Date(props.rental.ship_out_time)
      const diffTime = startDate.getTime() - shipOutTime.getTime()
      logisticsDays = Math.max(1, Math.ceil(diffTime / (1000 * 60 * 60 * 24)) - 1)
    }

    // 使用 X200U 型号 (ID: 1) 查找可用的手柄附件
    const slotResponse = await ganttStore.findAvailableSlot(
      props.rental.start_date,
      props.rental.end_date,
      logisticsDays,
      1, // X200U 型号 ID
      true // is_accessory
    )

    // 更新所有手柄的状态
    availableControllers.value.forEach(accessory => {
      if (accessory.model && accessory.model.includes('手柄')) {
        // API 返回的可用设备ID在 available_devices 数组中
        if (slotResponse.availableDevices && slotResponse.availableDevices.includes(accessory.id)) {
          accessory.isAvailable = true
          accessory.conflictReason = undefined
        } else {
          accessory.isAvailable = false
          accessory.conflictReason = '档期冲突'
        }
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
  // 只在首次点击时检查附件冲突
  if (!accessoryConflictChecked.value) {
    await findAvailableAccessory() // 复用查找手柄的逻辑
    accessoryConflictChecked.value = true
  }
}

const handleAccessoryChange = async (accessoryIds: number[]) => {
  // 当用户选择/取消选择附件时，检查新选择的附件的档期冲突
  const newAccessoryIds = accessoryIds.filter(id => !form.value.accessories.includes(id))

  for (const accessoryId of newAccessoryIds) {
    const accessory = availableControllers.value.find(a => a.id === accessoryId)
    if (accessory) {
      // 如果还没检查过冲突，先检查
      if (!accessoryConflictChecked.value) {
        await checkAccessoryConflict(accessory)
      }

      // 如果有冲突，警告用户
      if (accessory.isAvailable === false) {
        ElMessageBox.confirm(
          `附件 "${accessory.name}" 在该时间段有冲突，确定要选择吗？`,
          '附件冲突警告',
          {
            confirmButtonText: '确定选择',
            cancelButtonText: '取消',
            type: 'warning',
          }
        ).catch(() => {
          // 用户取消，从选择中移除该附件
          form.value.accessories = form.value.accessories.filter(id => id !== accessoryId)
        })
      }
    }
  }
}

const openContract = () => {
  if (props.rental) {
    // 跳转到合同页面
    const url = router.resolve({ path: `/contract/${props.rental.id}` })
    window.open(url.href, '_blank')
  }
}

const openShippingOrder = () => {
  if (props.rental) {
    // 跳转到发货单页面
    const url = router.resolve({ path: `/shipping/${props.rental.id}` })
    window.open(url.href, '_blank')
  }
}

// 加载所有设备（不预先检查冲突）
const loadAvailableDevices = async () => {
  loadingDevices.value = true
  try {
    // 直接使用 ganttStore 中的设备数据，过滤出非附件设备
    availableDevices.value = ganttStore.devices.filter(device => !device.is_accessory)
  } catch (error) {
    console.error('加载设备列表失败:', error)
    ElMessage.error('加载设备列表失败')
  } finally {
    loadingDevices.value = false
  }
}

// 懒加载设备冲突检查（只在用户展开设备选择器时调用）
const checkDevicesConflictOnDemand = async () => {
  if (!props.rental) return

  loadingDevices.value = true
  try {
    // 使用租赁的实际寄出和收回时间进行冲突检查
    const shipOutTime = props.rental.ship_out_time || props.rental.start_date
    const shipInTime = props.rental.ship_in_time || props.rental.end_date

    const conflictCheckPromises = availableDevices.value.map(async (device) => {
      // 检查当前设备是否与其他租赁有时间冲突
      const hasConflict = await checkDeviceConflict(
        device.id,
        shipOutTime,
        shipInTime,
        props.rental!.id // 排除当前租赁
      )

      return {
        ...device,
        conflicted: hasConflict
      }
    })

    availableDevices.value = await Promise.all(conflictCheckPromises)
  } catch (error) {
    console.error('检查设备冲突失败:', error)
  } finally {
    loadingDevices.value = false
  }
}

// 检查设备时间冲突
const checkDeviceConflict = async (deviceId: number, startDate: string, endDate: string, excludeRentalId?: number) => {
  try {
    const response = await axios.post('/api/rentals/check-conflict', {
      device_id: deviceId,
      ship_out_time: startDate,
      ship_in_time: endDate,
      exclude_rental_id: excludeRentalId
    })

    return response.data.data.has_conflicts || false
  } catch (error) {
    console.error('检查设备冲突失败:', error)
    return false
  }
}

// 缓存设备型号数据
let deviceModelsCache: any[] | null = null

// 获取设备型号列表（带缓存）
const getDeviceModels = async () => {
  if (!deviceModelsCache) {
    try {
      const response = await axios.get('/api/device-models')
      if (response.data.success) {
        deviceModelsCache = response.data.data
      }
    } catch (error) {
      console.error('获取设备型号列表失败:', error)
    }
  }
  return deviceModelsCache || []
}

// 根据 model 名称查找对应的 model_id
const findModelIdByName = async (modelName: string): Promise<number | null> => {
  const models = await getDeviceModels()
  const matchingModel = models.find((model: any) => {
    return model.accessories?.some((acc: any) => {
      const accName = acc.accessory_name.toLowerCase().replace(/\s+/g, '')
      const deviceModel = modelName.toLowerCase().replace(/\s+/g, '')
      // 检查是否匹配，支持模糊匹配
      return accName === deviceModel ||
             deviceModel.includes(accName) ||
             accName.includes(deviceModel.replace('专用', ''))
    })
  })
  return matchingModel ? matchingModel.id : null
}

// 加载附件列表（不检查档期冲突）
const loadAvailableAccessories = async () => {
  if (!props.rental) return

  loadingAccessories.value = true
  try {
    // 获取所有设备，先筛选出附件设备
    const response = await axios.get('/api/devices')

    if (response.data.success) {
      // 先获取所有附件设备，不检查档期
      const allAccessories = response.data.data.filter((device: Device) =>
        device.is_accessory && device.model
      )

      // 为每个附件添加基础状态（不调用 API 检查冲突）
      const accessoriesWithStatus: AccessoryWithStatus[] = allAccessories.map((accessory: Device) => ({
        ...accessory,
        isAvailable: true,
        conflictReason: undefined
      }))

      availableControllers.value = accessoriesWithStatus
    } else {
      console.error('获取附件列表失败:', response.data.error)
      ElMessage.error('获取附件列表失败')
    }
  } catch (error) {
    console.error('获取附件列表失败:', error)
    ElMessage.error('获取附件列表失败')
  } finally {
    loadingAccessories.value = false
  }
}

// 按需检查特定附件的档期冲突
const checkAccessoryConflict = async (accessory: AccessoryWithStatus) => {
  if (!props.rental) return

  try {
    // 获取设备的 model_id
    let modelId = accessory.device_model?.id || accessory.model_id

    // 如果没有 model_id，根据 model 名称查找
    if (!modelId && accessory.model) {
      const foundModelId = await findModelIdByName(accessory.model)
      if (foundModelId) {
        modelId = foundModelId
      }
    }

    // 如果找到了 model_id，检查档期冲突
    if (modelId) {
      // 计算物流天数
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
        modelId,
        true // is_accessory
      )

      // 更新附件状态
      if (slotResponse.device) {
        accessory.isAvailable = true
        accessory.conflictReason = undefined
      } else {
        accessory.isAvailable = false
        accessory.conflictReason = '档期冲突'
      }
    } else {
      // 没有找到 model_id
      accessory.isAvailable = true
      accessory.conflictReason = '无法检查档期'
    }
  } catch (error) {
    console.error('检查附件档期失败:', error)
    accessory.isAvailable = false
    accessory.conflictReason = '检查档期失败'
  }
}

// 获取最新的租赁数据
const loadLatestRentalData = async () => {
  if (!props.rental) return null

  loadingLatestData.value = true
  latestDataError.value = null

  try {
    const response = await axios.get(`/api/rentals/${props.rental.id}`)
    if (response.data.success) {
      return response.data.data
    } else {
      throw new Error(response.data.error || '获取租赁数据失败')
    }
  } catch (error: any) {
    console.error('获取最新租赁数据失败:', error)
    latestDataError.value = error.message || '获取最新数据失败'
    return props.rental // fallback to cached data
  } finally {
    loadingLatestData.value = false
  }
}

// 初始化表单数据
const initForm = async () => {
  if (props.rental) {
    // 重置冲突检查标志
    deviceConflictChecked.value = false
    accessoryConflictChecked.value = false

    // 获取最新数据
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
      accessories: (rentalData.child_rentals || []).map((child: any) => child.device_id).filter(Boolean)
    }

    // 使用最新数据加载可用附件
    if (latestRental) {
      // 更新 props.rental 的引用以便其他函数使用最新数据
      Object.assign(props.rental, latestRental)
    }

    // 加载设备列表和附件列表
    await Promise.all([
      loadAvailableDevices(),
      loadAvailableAccessories()
    ])
  }
}

// 监听器
watch(() => props.rental, () => {
  if (props.rental) {
    initForm()
  }
}, { immediate: true })

watch(() => props.modelValue, (newValue) => {
  if (newValue && props.rental) {
    initForm()
  }
})
</script>

<style scoped>
.dialog-footer {
  text-align: right;
}
</style>