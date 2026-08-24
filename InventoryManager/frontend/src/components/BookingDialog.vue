<template>
  <el-dialog
    v-model="dialogVisible"
    title="预定设备"
    width="600px"
    :close-on-click-modal="false"
    :close-on-press-escape="!submitting"
    :show-close="!submitting"
    @close="handleClose"
    @closed="handleClosed"
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

      <el-form-item label="优先仓库">
        <el-select
          v-model="form.preferredWarehouseId"
          placeholder="请选择优先仓库"
          style="width: 100%"
          @change="scheduleAvailability"
        >
          <el-option
            v-for="warehouse in booking.bootstrap.value?.warehouses ?? []"
            :key="warehouse.id"
            :label="`${warehouse.name} · ${warehouse.address_summary}`"
            :value="warehouse.id"
          />
        </el-select>
        <div class="form-tip">优先仓只影响排序，实际起点由最终设备所在仓决定</div>
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

      <el-form-item label="设备型号" prop="selectedModelId">
        <el-select
          v-model="form.selectedModelId"
          placeholder="请选择设备型号"
          style="width: 100%"
          clearable
          filterable
          @change="handleModelChange"
        >
          <el-option
            v-for="model in availableDeviceModels"
            :key="model.id"
            :label="model.display_name"
            :value="model.id"
          />
        </el-select>
        <div class="form-tip">默认使用甘特图当前型号，可在此处单独修改</div>
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

      <el-form-item v-if="manualLogisticsRequired" label="物流确认">
        <el-alert
          type="warning"
          :closable="false"
          :title="`官方估算不可用，请确认按 ${form.logisticsDays} 天预留`"
        />
        <el-button
          type="warning"
          :loading="booking.availabilityLoading.value"
          style="margin-top: 8px"
          @click="confirmManualLogistics"
        >
          确认物流天数
        </el-button>
      </el-form-item>

      <!-- 闲鱼订单信息 -->
      <el-form-item label="闲鱼订单号">
        <div style="display: flex; gap: 8px;">
          <el-input
            v-model="form.xianyuOrderNo"
            placeholder="请输入闲鱼订单号"
            style="flex: 1;"
          />
          <el-button
            type="primary"
            @click="handleFetchOrderInfo"
            :loading="fetchingOrder"
          >
            拉取订单信息
          </el-button>
        </div>
        <div class="form-tip">输入订单号后点击按钮可自动填充收件人、地址等信息</div>
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
              v-for="device in filteredDevices"
              :key="device.id"
              :label="device.name"
              :value="device.id"
              :disabled="device.available !== true"
            >
              <div class="device-option">
                <span>{{ device.name }}</span>
                <div class="device-status">
                  <span class="device-model">{{ device.warehouse_name }}</span>
                  <el-tag
                    v-if="device.available"
                    type="success"
                    size="small"
                    effect="dark"
                  >
                    可用
                  </el-tag>
                  <el-tag
                    v-else
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

      <el-form-item label="省" prop="customerProvince">
        <el-input
          v-model="form.customerProvince"
          placeholder="例如：广东省"
        />
      </el-form-item>

      <el-form-item label="市" prop="customerCity">
        <el-input v-model="form.customerCity" placeholder="例如：深圳市" />
      </el-form-item>

      <el-form-item label="区县" prop="customerDistrict">
        <el-input v-model="form.customerDistrict" placeholder="例如：南山区" />
      </el-form-item>

      <el-form-item label="详细地址" prop="customerAddressDetail">
        <el-input
          v-model="form.customerAddressDetail"
          type="textarea"
          :rows="2"
          placeholder="街道、门牌号等"
        />
      </el-form-item>

      <el-form-item label="订单金额(元)">
        <el-input
          v-model="form.orderAmount"
          placeholder="请输入订单金额"
          type="number"
        />
        <div class="form-tip">用于收入统计</div>
      </el-form-item>

      <el-form-item label="买家ID">
        <el-input
          v-model="form.buyerId"
          placeholder="买家闲鱼EID"
          disabled
        />
        <div class="form-tip">从订单信息自动获取</div>
      </el-form-item>

      <!-- 配套附件 - 复选框 -->
      <el-form-item label="配套附件">
        <el-checkbox-group v-model="form.bundledAccessories">
          <el-checkbox label="handle">手柄</el-checkbox>
          <el-checkbox label="lens_mount">镜头支架</el-checkbox>
        </el-checkbox-group>
        <div class="form-tip">手柄和镜头支架已与设备配齐，无需选择具体编号</div>
      </el-form-item>

      <!-- 镜头组合 -->
      <LensComboSelector
        v-model="form.lensCombo"
        :model-name="selectedModelName"
      />

      <!-- 代传照片 - 复选框 -->
      <el-form-item label="附加服务">
        <el-checkbox v-model="form.photoTransfer">代传照片</el-checkbox>
        <div class="form-tip">勾选此项表示需要代替客户传输照片</div>
      </el-form-item>

      <el-form-item v-if="logicalAccessoryTypes.length" label="库存附件">
        <el-checkbox-group v-model="form.requestedAccessoryTypeIds">
          <el-checkbox
            v-for="accessoryType in logicalAccessoryTypes"
            :key="accessoryType.id"
            :label="accessoryType.id"
            :disabled="!canRequestAccessory(accessoryType.id)"
          >
            {{ accessoryTypeLabel(accessoryType.id) }}
          </el-checkbox>
        </el-checkbox-group>
        <div class="form-tip">只选择附件类型，系统在最终事务中自动分配同仓逻辑单元</div>
      </el-form-item>

      <!-- 查找到的档期信息 -->
      <div v-if="availableSlot" class="slot-info">
        <div class="slot-device">
          <el-icon><Monitor /></el-icon>
          已找到可用设备: {{ availableSlot.device?.name || '未知设备' }}
        </div>
        <div class="slot-times">
          <div>寄出时间: {{ availableSlot.planned_ship_out_date || '待物流确认' }}</div>
          <div>收回时间: {{ availableSlot.planned_return_date || '待物流确认' }}</div>
        </div>
      </div>
    </el-form>

    <template #footer>
      <div class="dialog-footer">
        <el-button :disabled="submitting" @click="handleClose">取消</el-button>
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
import { ref, computed, watch, nextTick, onBeforeUnmount } from 'vue'
import { ElMessage, ElMessageBox, type FormInstance } from 'element-plus'
import { Monitor } from '@element-plus/icons-vue'
import VueDatePicker from '@vuepic/vue-datepicker'
import '@vuepic/vue-datepicker/dist/main.css'
import dayjs from 'dayjs'
import axios from 'axios'

// 导入组合式函数
import { useGanttStore } from '@/stores/gantt'
import { useConflictDetection } from '@/composables/useConflictDetection'
import { getCreateRentalRules } from '@/composables/useRentalFormValidation'
import {
  useRentalBooking,
  type BookingAccessoryType,
  type BookingAvailabilityPayload,
  type BookingCandidate,
} from '@/composables/useRentalBooking'
import LensComboSelector from './rental/LensComboSelector.vue'

// Props & Emits
interface Props {
  modelValue: boolean
  selectedDeviceModel?: string // 当前甘特图选择的设备型号 display_name
  initialXianyuOrderNo?: string
}

const props = defineProps<Props>()
const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  'success': [rentalId?: number]
}>()

// Store & Composables
const ganttStore = useGanttStore()
const conflictDetection = useConflictDetection()
const booking = useRentalBooking()

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
  selectedModelId: null as number | null,
  preferredWarehouseId: null as number | null,
  selectedDeviceId: null as number | null,
  customerName: '',
  customerPhone: '',
  destination: '',
  customerProvince: '',
  customerCity: '',
  customerDistrict: '',
  customerAddressDetail: '',
  // 新：分离配套附件和库存附件
  bundledAccessories: [] as ('handle' | 'lens_mount')[],
  requestedAccessoryTypeIds: [] as number[],
  xianyuOrderNo: '',
  orderAmount: '',
  buyerId: '',
  photoTransfer: false,  // 代传照片标记
  lensCombo: undefined as ('lens_400mm' | 'lens_200mm' | 'bare' | 'lens_dual' | undefined)
})

const availableDeviceModels = computed(() =>
  booking.bootstrap.value?.device_models ?? []
)

const selectedModel = computed(() =>
  availableDeviceModels.value.find(
    model => model.id === form.value.selectedModelId
  ) || null
)

const filteredDevices = computed(() =>
  (booking.availability.value?.candidates ?? []).map(candidate => ({
    ...candidate.device,
    available: candidate.available,
    warehouse_name: candidate.warehouse.name,
  }))
)

// 当前所选型号的 short name（用于镜头组合选项）
const selectedModelName = computed<string | null>(() =>
  selectedModel.value?.name || null
)

// UI State
const submitting = ref(false)
const pendingSuccess = ref<{ rentalId: number } | null>(null)
const dialogClosed = ref(!props.modelValue)
const searching = ref(false)
const fetchingOrder = ref(false)
const availableSlot = ref<BookingCandidate | null>(null)
const manualLogisticsByWarehouse = ref<NonNullable<
  BookingAvailabilityPayload['manual_logistics_by_warehouse']
>>({})
let availabilityTimer: ReturnType<typeof setTimeout> | undefined

onBeforeUnmount(() => {
  if (availabilityTimer) clearTimeout(availabilityTimer)
  availabilityTimer = undefined
})

const invalidateSlotSearch = () => {
  booking.resetAvailability()
  if (availabilityTimer) clearTimeout(availabilityTimer)
  searching.value = false
}

// Form Rules
const rules = getCreateRentalRules()

// Computed
const canSearchSlot = computed(() => {
  return Boolean(
    form.value.startDate &&
    form.value.endDate &&
    form.value.logisticsDays >= 0 &&
    form.value.selectedModelId &&
    form.value.customerProvince.trim() &&
    form.value.customerCity.trim() &&
    form.value.customerDistrict.trim() &&
    form.value.customerAddressDetail.trim()
  )
})

const selectedCandidate = computed(() =>
  booking.availability.value?.candidates.find(
    candidate => candidate.device.id === form.value.selectedDeviceId,
  ) ?? null
)

const logicalAccessoryTypes = computed<BookingAccessoryType[]>(() => {
  const configuredIds = new Set(
    selectedCandidate.value?.accessories
      .filter(item => item.tracking_mode === 'logical_unit')
      .map(item => item.accessory_type_id) ?? [],
  )
  return (booking.bootstrap.value?.accessory_types ?? []).filter(
    item => item.tracking_mode === 'logical_unit' && configuredIds.has(item.id),
  )
})

const accessoryFact = (accessoryTypeId: number) =>
  selectedCandidate.value?.accessories.find(
    item => item.accessory_type_id === accessoryTypeId,
  ) ?? null

const canRequestAccessory = (accessoryTypeId: number) => {
  const fact = accessoryFact(accessoryTypeId)
  if (!fact) return false
  return Boolean(
    (fact.available ?? 0) > 0
    || fact.relay_confirmation_required
    || (fact.shortage && selectedCandidate.value?.relay_candidate)
  )
}

const accessoryTypeLabel = (accessoryTypeId: number) => {
  const type = logicalAccessoryTypes.value.find(
    item => item.id === accessoryTypeId,
  )
  const fact = accessoryFact(accessoryTypeId)
  if (!type || !fact) return type?.display_name ?? '附件'
  if (fact.relay_confirmation_required) {
    return `${type.display_name}（接力确认后可满足）`
  }
  if (fact.shortage) return `${type.display_name}（库存不足）`
  return `${type.display_name}（可用 ${fact.available ?? 0}）`
}

const manualLogisticsRequired = computed(() =>
  Object.values(
    booking.availability.value?.estimate_by_warehouse ?? {},
  ).some(estimate => estimate.manual_confirmation_required)
)

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

// Date Change Handlers
const handleStartDateChange = (date: Date | null) => {
  form.value.startDate = date
  if (date && form.value.endDate && dayjs(form.value.endDate).isBefore(dayjs(date))) {
    form.value.endDate = null
  }

  availableSlot.value = null
  scheduleAvailability()
}

const handleEndDateChange = (date: Date | null) => {
  form.value.endDate = date
  availableSlot.value = null
  scheduleAvailability()
}

const structuredDestination = () => ({
  province: form.value.customerProvince.trim(),
  city: form.value.customerCity.trim(),
  district: form.value.customerDistrict.trim(),
  address_detail: form.value.customerAddressDetail.trim(),
})

const syncLegacyDestination = () => {
  const destination = structuredDestination()
  form.value.destination = [
    destination.province,
    destination.city,
    destination.district,
    destination.address_detail,
  ].join('')
}

const checkAvailabilities = async () => {
  if (!canSearchSlot.value || !form.value.startDate || !form.value.endDate) {
    booking.resetAvailability()
    return null
  }
  const priorDeviceId = form.value.selectedDeviceId
  try {
    const result = await booking.evaluateAvailability({
      start_date: dayjs(form.value.startDate).format('YYYY-MM-DD'),
      end_date: dayjs(form.value.endDate).format('YYYY-MM-DD'),
      model_id: Number(form.value.selectedModelId),
      preferred_warehouse_id: form.value.preferredWarehouseId,
      destination: structuredDestination(),
      requested_accessory_type_ids: [
        ...form.value.requestedAccessoryTypeIds,
      ].sort((left, right) => left - right),
      ...(Object.keys(manualLogisticsByWarehouse.value).length
        ? { manual_logistics_by_warehouse: manualLogisticsByWarehouse.value }
        : {}),
    })
    if (!result) return null
    if (!result.candidates.some(
      candidate => candidate.device.id === priorDeviceId && candidate.available,
    )) {
      form.value.selectedDeviceId = null
      form.value.requestedAccessoryTypeIds = []
      availableSlot.value = null
    } else {
      availableSlot.value = selectedCandidate.value
    }
    return result
  } catch (error) {
    form.value.selectedDeviceId = null
    form.value.requestedAccessoryTypeIds = []
    availableSlot.value = null
    ElMessage.error((error as Error).message || '无法确认设备可用性')
    return null
  }
}

const scheduleAvailability = () => {
  if (availabilityTimer) clearTimeout(availabilityTimer)
  availabilityTimer = setTimeout(() => {
    void checkAvailabilities()
  }, 250)
}

const handleModelChange = (modelId: number | null | undefined) => {
  form.value.selectedModelId = modelId ?? null
  form.value.selectedDeviceId = null
  form.value.requestedAccessoryTypeIds = []
  availableSlot.value = null
  scheduleAvailability()
}

// Device Focus Handler
const handleDeviceFocus = async () => {
  if (!form.value.selectedModelId) {
    ElMessage.warning('请先选择设备型号')
    return
  }

  if (!form.value.startDate || !form.value.endDate) {
    ElMessage.warning('请先选择日期后查看设备可用性')
    return
  }

  if (!booking.availability.value) {
    await checkAvailabilities()
  }
}

// Find Available Slot
const findAvailableSlot = async () => {
  if (!form.value.selectedModelId) {
    ElMessage.warning('请先选择设备型号')
    return
  }

  if (!form.value.startDate || !form.value.endDate || form.value.logisticsDays < 0) {
    ElMessage.warning('请先完善日期和物流信息')
    return
  }

  searching.value = true
  try {
    const result = await checkAvailabilities()
    const candidate = result?.candidates.find(
      item => item.available && item.submission_ready,
    ) ?? result?.candidates.find(item => item.available)
    if (candidate) {
      form.value.selectedDeviceId = candidate.device.id
      form.value.requestedAccessoryTypeIds = []
      availableSlot.value = candidate
      ElMessage.success(`找到可用设备: ${candidate.device.name}`)
    } else {
      throw new Error('在指定时间段内没有可用设备')
    }
  } catch (error) {
    ElMessage.error((error as Error).message)
    availableSlot.value = null
  } finally {
    searching.value = false
  }
}

const confirmManualLogistics = async () => {
  const estimates = booking.availability.value?.estimate_by_warehouse ?? {}
  manualLogisticsByWarehouse.value = Object.fromEntries(
    Object.entries(estimates).map(([warehouseId, estimate]) => [
      warehouseId,
      {
        days: form.value.logisticsDays,
        context: estimate.confirmation_context,
      },
    ]),
  )
  await checkAvailabilities()
}

watch([
  () => form.value.customerProvince,
  () => form.value.customerCity,
  () => form.value.customerDistrict,
  () => form.value.customerAddressDetail,
  () => form.value.logisticsDays,
], () => {
  manualLogisticsByWarehouse.value = {}
  scheduleAvailability()
})

watch(
  () => form.value.requestedAccessoryTypeIds.join(','),
  scheduleAvailability,
)

watch(() => form.value.selectedDeviceId, (deviceId, priorDeviceId) => {
  if (
    priorDeviceId !== null
    && deviceId !== priorDeviceId
    && form.value.requestedAccessoryTypeIds.length
  ) {
    form.value.requestedAccessoryTypeIds = []
  }
  availableSlot.value = selectedCandidate.value
})

// 拉取闲鱼订单信息
const handleFetchOrderInfo = async () => {
  const orderNo = form.value.xianyuOrderNo?.trim()

  if (!orderNo) {
    ElMessage.warning('请先输入订单号')
    return
  }

  fetchingOrder.value = true

  try {
    const response = await axios.post('/api/rentals/fetch-xianyu-order', {
      order_no: orderNo
    })

    if (response.data.success && response.data.data) {
      const orderData = response.data.data
      if (orderData.buyer_nick) {
        form.value.customerName = orderData.buyer_nick
      }
      form.value.customerProvince = (
        orderData.prov_name || form.value.customerProvince
      )
      form.value.customerCity = (
        orderData.city_name || form.value.customerCity
      )
      form.value.customerDistrict = (
        orderData.area_name || form.value.customerDistrict
      )
      form.value.customerAddressDetail = [
        orderData.town_name,
        orderData.address,
      ].filter(Boolean).join('') || form.value.customerAddressDetail
      syncLegacyDestination()
      if (orderData.buyer_eid) {
        form.value.buyerId = orderData.buyer_eid
      }
      if (orderData.pay_amount) {
        form.value.orderAmount = (orderData.pay_amount / 100).toFixed(2)
      }
      if (orderData.receiver_mobile) {
        form.value.customerPhone = orderData.receiver_mobile
      }

      ElMessage.success('订单信息获取成功')
    } else {
      ElMessage.error(response.data.message || '获取订单信息失败')
    }
  } catch (error: any) {
    console.error('获取订单信息失败:', error)
    ElMessage.error(error.response?.data?.message || '获取订单信息失败，请检查订单号是否正确')
  } finally {
    fetchingOrder.value = false
  }
}

// Submit Handler
const handleSubmit = async () => {
  try {
    await formRef.value?.validate()
  } catch {
    return
  }
  const candidate = selectedCandidate.value
  if (!candidate?.available) {
    ElMessage.error('请选择当前可用的设备')
    return
  }
  if (!candidate.submission_ready) {
    ElMessage.error('请先完成物流天数确认')
    return
  }
  syncLegacyDestination()

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
    const deviceId = form.value.selectedDeviceId
    if (!deviceId) {
      ElMessage.error('请选择设备')
      return
    }

    const rentalData = {
      device_id: deviceId,
      model_id: form.value.selectedModelId,
      expected_origin_warehouse_id: candidate.warehouse.id,
      preferred_warehouse_id: form.value.preferredWarehouseId,
      start_date: dayjs(form.value.startDate).format('YYYY-MM-DD'),
      end_date: dayjs(form.value.endDate).format('YYYY-MM-DD'),
      customer_name: form.value.customerName,
      customer_phone: form.value.customerPhone,
      destination: structuredDestination(),
      legacy_destination: form.value.destination,
      customer_province: form.value.customerProvince.trim(),
      customer_city: form.value.customerCity.trim(),
      customer_district: form.value.customerDistrict.trim(),
      customer_address_detail: form.value.customerAddressDetail.trim(),
      logistics_days: form.value.logisticsDays,
      includes_handle: form.value.bundledAccessories.includes('handle'),
      includes_lens_mount: form.value.bundledAccessories.includes('lens_mount'),
      accessories: [],
      requested_accessory_type_ids: [
        ...form.value.requestedAccessoryTypeIds,
      ].sort((left, right) => left - right),
      manual_logistics_by_warehouse: manualLogisticsByWarehouse.value,
      xianyu_order_no: form.value.xianyuOrderNo,
      order_amount: form.value.orderAmount ? parseFloat(form.value.orderAmount) : undefined,
      buyer_id: form.value.buyerId,
      photo_transfer: form.value.photoTransfer,
      ...(form.value.lensCombo
        ? { lens_combo: form.value.lensCombo }
        : {})
    }

    const result = await ganttStore.createRental(rentalData)
    const rentalId = result.data?.main_rental?.id
    ElMessage.success('租赁记录创建成功')
    if (typeof rentalId === 'number') {
      queuePendingSuccess({ rentalId })
    } else {
      pendingSuccess.value = null
      ElMessage.error('保存成功，但确认信息加载失败')
      if (!dialogClosed.value) handleClose()
    }
  } catch (error: any) {
    ElMessage.error('创建失败：' + (error.message || '未知错误'))
  } finally {
    submitting.value = false
  }
}

// Close Handler
const handleClose = () => {
  invalidateSlotSearch()
  formRef.value?.resetFields()
  form.value = {
    startDate: null,
    endDate: null,
    logisticsDays: 1,
    selectedModelId: null,
    preferredWarehouseId: null,
    selectedDeviceId: null,
    customerName: '',
    customerPhone: '',
    destination: '',
    customerProvince: '',
    customerCity: '',
    customerDistrict: '',
    customerAddressDetail: '',
    bundledAccessories: [],
    requestedAccessoryTypeIds: [],
    xianyuOrderNo: '',
    orderAmount: '',
    buyerId: '',
    photoTransfer: false,
    lensCombo: undefined
  }
  availableSlot.value = null
  manualLogisticsByWarehouse.value = {}
  booking.resetAvailability()
  emit('update:modelValue', false)
}

const handleClosed = () => {
  dialogClosed.value = true
  flushPendingSuccess()
}

const flushPendingSuccess = () => {
  if (!dialogClosed.value) return
  const success = pendingSuccess.value
  if (!success) return

  pendingSuccess.value = null
  emit('success', success.rentalId)
}

const queuePendingSuccess = (success: { rentalId: number }) => {
  pendingSuccess.value = success
  if (dialogClosed.value) {
    flushPendingSuccess()
  } else {
    handleClose()
  }
}

// Watch Dialog Open
watch(() => props.modelValue, async (visible) => {
  if (visible) {
    dialogClosed.value = false
    pendingSuccess.value = null
    let bootstrap
    try {
      bootstrap = await booking.loadBootstrap()
    } catch {
      ElMessage.error('预约表单加载失败，请稍后重试')
      return
    }
    form.value.preferredWarehouseId = (
      bootstrap.recent_warehouse_id
      ?? bootstrap.default_warehouse_id
      ?? bootstrap.warehouses[0]?.id
      ?? null
    )
    form.value.selectedModelId = bootstrap.device_models.find(
      model => model.display_name === props.selectedDeviceModel
    )?.id ?? null
    if (props.initialXianyuOrderNo) {
      form.value.xianyuOrderNo = props.initialXianyuOrderNo
      await nextTick()
      await handleFetchOrderInfo()
    }
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
