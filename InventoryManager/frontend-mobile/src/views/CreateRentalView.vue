<template>
  <div class="form-view">
    <van-nav-bar
      title="新建租赁"
      left-arrow
      @click-left="$router.back()"
      :border="false"
    />

    <div class="form-scroll">
      <van-form ref="formRef" @submit="onSubmit">
        <!-- 闲鱼订单号 -->
        <van-cell-group inset title="订单信息">
          <van-field
            v-model="form.xianyuOrderNo"
            label="闲鱼订单号"
            placeholder="选填，可自动填充客户信息"
            clearable
          >
            <template #button>
              <van-button
                size="small"
                type="primary"
                :loading="fetchingOrder"
                @click="fetchOrderInfo"
              >拉取</van-button>
            </template>
          </van-field>

          <van-field
            v-model="form.customerName"
            label="客户姓名"
            placeholder="请输入"
            required
            :rules="[{ required: true, message: '请填写客户姓名' }]"
          />
          <van-field
            v-model="form.customerPhone"
            label="客户电话"
            placeholder="请输入"
            type="tel"
          />
          <van-field
            v-model="form.customerProvince"
            label="省"
            placeholder="例如：广东省"
            required
            :rules="[{ required: true, message: '请填写省' }]"
          />
          <van-field
            v-model="form.customerCity"
            label="市"
            placeholder="例如：深圳市"
            required
            :rules="[{ required: true, message: '请填写市' }]"
          />
          <van-field
            v-model="form.customerDistrict"
            label="区县"
            placeholder="例如：南山区"
            required
            :rules="[{ required: true, message: '请填写区县' }]"
          />
          <van-field
            v-model="form.customerAddressDetail"
            label="详细地址"
            placeholder="街道、门牌号等"
            type="textarea"
            rows="2"
            autosize
            required
            :rules="[{ required: true, message: '请填写详细地址' }]"
          />
          <van-field
            v-model="form.orderAmount"
            label="订单金额"
            placeholder="选填"
            type="number"
          />
          <van-field
            v-model="form.buyerId"
            label="买家ID"
            placeholder="选填"
          />
        </van-cell-group>

        <!-- 租赁信息 -->
        <van-cell-group inset title="租赁日期" style="margin-top:12px">
          <!-- 设备型号 -->
          <van-field
            v-model="selectedModelName"
            readonly
            clickable
            label="设备型号"
            placeholder="请选择"
            required
            :rules="[{ required: true, message: '请选择设备型号' }]"
            @click="showModelPicker = true"
          />

          <van-field
            v-model="selectedWarehouseName"
            readonly
            clickable
            label="优先仓库"
            placeholder="请选择"
            @click="showWarehousePicker = true"
          />

          <!-- 起租日 -->
          <van-field
            v-model="form.startDate"
            readonly
            clickable
            label="起租日"
            placeholder="请选择"
            required
            :rules="[{ required: true, message: '请选择起租日' }]"
            @click="showStartDatePicker = true"
          />

          <!-- 还租日 -->
          <van-field
            v-model="form.endDate"
            readonly
            clickable
            label="还租日"
            placeholder="请选择"
            required
            :rules="[{ required: true, message: '请选择还租日' }]"
            @click="showEndDatePicker = true"
          />

          <!-- 物流天数 -->
          <van-field label="物流天数">
            <template #input>
              <van-stepper v-model="form.logisticsDays" :min="0" :max="7" />
            </template>
          </van-field>

          <van-cell
            v-if="manualLogisticsRequired"
            title="物流估算不可用"
            :label="`请确认按 ${form.logisticsDays} 天预留物流时间`"
          >
            <template #right-icon>
              <van-button
                size="small"
                type="warning"
                :loading="checkingSlots"
                @click="confirmManualLogistics"
              >确认</van-button>
            </template>
          </van-cell>

          <!-- 发货时间（只读） -->
          <van-cell title="发货时间" :value="shipOutDisplay" />
          <!-- 入库时间（只读） -->
          <van-cell title="入库时间" :value="shipInDisplay" />

          <!-- 可用设备 -->
          <van-field
            v-model="selectedDeviceName"
            readonly
            clickable
            label="可用设备"
            :placeholder="availableSlots.length ? '请选择' : '先选择日期和型号'"
            @click="availableSlots.length && (showDevicePicker = true)"
          >
            <template #right-icon>
              <van-loading v-if="checkingSlots" size="16" />
            </template>
          </van-field>
        </van-cell-group>

        <!-- 镜头组合 -->
        <van-cell-group inset title="镜头组合" style="margin-top:12px">
          <van-field label="组合">
            <template #input>
              <van-radio-group v-model="lensComboModel" direction="horizontal" class="combo-radio-group">
                <van-tag
                  v-for="opt in allowedCombos"
                  :key="opt"
                  :type="lensComboModel === opt ? 'primary' : 'default'"
                  :plain="lensComboModel !== opt"
                  size="medium"
                  class="combo-chip"
                  @click="lensComboModel = opt"
                >
                  {{ comboLabel(opt) }}
                </van-tag>
              </van-radio-group>
            </template>
          </van-field>
        </van-cell-group>

        <!-- 配件 -->
        <van-cell-group inset title="配件" style="margin-top:12px">
          <van-field label="随机配件">
            <template #input>
              <van-checkbox-group v-model="form.bundledAccessories" direction="horizontal">
                <van-checkbox name="handle" shape="square">手柄</van-checkbox>
                <van-checkbox name="lens_mount" shape="square" style="margin-left:12px">镜头座</van-checkbox>
              </van-checkbox-group>
            </template>
          </van-field>

          <van-field
            v-if="logicalAccessoryTypes.length"
            label="库存配件"
          >
            <template #input>
              <van-checkbox-group
                v-model="form.requestedAccessoryTypeIds"
                direction="horizontal"
              >
                <van-checkbox
                  v-for="accessoryType in logicalAccessoryTypes"
                  :key="accessoryType.id"
                  :name="accessoryType.id"
                  shape="square"
                  :disabled="!canRequestAccessory(accessoryType.id)"
                >
                  {{ accessoryTypeLabel(accessoryType.id) }}
                </van-checkbox>
              </van-checkbox-group>
            </template>
          </van-field>

          <van-field label="代传照片">
            <template #input>
              <van-switch v-model="form.photoTransfer" size="20" />
            </template>
          </van-field>
        </van-cell-group>

        <!-- 提交 -->
        <div class="submit-wrap">
          <van-button
            type="primary"
            block
            native-type="submit"
            :loading="submitting"
            data-testid="create-rental"
          >创建租赁</van-button>
        </div>
      </van-form>
    </div>

    <!-- 型号选择器 -->
    <van-popup v-model:show="showModelPicker" position="bottom" round>
      <van-picker
        :columns="modelColumns"
        @confirm="onModelConfirm"
        @cancel="showModelPicker = false"
        show-toolbar
        title="选择设备型号"
      />
    </van-popup>

    <!-- 设备选择器 -->
    <van-popup v-model:show="showDevicePicker" position="bottom" round>
      <van-picker
        :columns="deviceColumns"
        @confirm="onDeviceConfirm"
        @cancel="showDevicePicker = false"
        show-toolbar
        title="选择可用设备"
      />
    </van-popup>

    <!-- 优先仓选择器 -->
    <van-popup v-model:show="showWarehousePicker" position="bottom" round>
      <van-picker
        :columns="warehouseColumns"
        @confirm="onWarehouseConfirm"
        @cancel="showWarehousePicker = false"
        show-toolbar
        title="选择优先仓库"
      />
    </van-popup>

    <!-- 起租日期选择器 -->
    <van-popup v-model:show="showStartDatePicker" position="bottom" round>
      <van-date-picker
        v-model="startDateParts"
        title="选择起租日"
        @confirm="onStartDateConfirm"
        @cancel="showStartDatePicker = false"
      />
    </van-popup>

    <!-- 还租日期选择器 -->
    <van-popup v-model:show="showEndDatePicker" position="bottom" round>
      <van-date-picker
        v-model="endDateParts"
        :min-date="endDateMin"
        title="选择还租日"
        @confirm="onEndDateConfirm"
        @cancel="showEndDatePicker = false"
      />
    </van-popup>

    <RentalConfirmationPopup
      v-if="savedRental"
      :rental="savedRental"
      @closed="handleConfirmationClosed"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onBeforeUnmount, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { showToast, showConfirmDialog } from 'vant'
import axios from 'axios'
import dayjs from 'dayjs'
import { useGanttStore } from '@/stores/gantt'
import type { Rental } from '@/stores/gantt'
import RentalConfirmationPopup from '@/components/RentalConfirmationPopup.vue'
import { useConflictDetection } from '@/composables/useConflictDetection'
import {
  useRentalBooking,
  type BookingAccessoryType,
  type BookingAvailabilityPayload,
  type BookingCandidate,
  type BookingDeviceModel,
} from '@/composables/useRentalBooking'
import {
  getAllowedCombos,
  getDefaultCombo,
  isComboAllowed,
  lensComboDisplay,
  type LensCombo,
} from '@/config/lensCombo'

const router = useRouter()
const route = useRoute()
const ganttStore = useGanttStore()
const conflictDetection = useConflictDetection()
const booking = useRentalBooking()

// 表单状态
const form = ref({
  xianyuOrderNo: '',
  customerName: '',
  customerPhone: '',
  destination: '',
  customerProvince: '',
  customerCity: '',
  customerDistrict: '',
  customerAddressDetail: '',
  orderAmount: '',
  buyerId: '',
  modelId: null as number | null,
  preferredWarehouseId: null as number | null,
  deviceId: null as number | null,
  startDate: '',
  endDate: '',
  logisticsDays: 1,
  bundledAccessories: [] as string[],
  requestedAccessoryTypeIds: [] as number[],
  photoTransfer: false,
  lensCombo: undefined as ('lens_400mm' | 'lens_200mm' | 'bare' | 'lens_dual' | undefined)
})

const formRef = ref()
const fetchingOrder = ref(false)
const submitting = ref(false)
const checkingSlots = booking.availabilityLoading
const savedRental = ref<Rental | null>(null)

// 日期选择器状态
const showStartDatePicker = ref(false)
const showEndDatePicker = ref(false)
const startDateParts = ref(dayjs().format('YYYY-MM-DD').split('-'))
const endDateParts = ref(dayjs().add(3, 'day').format('YYYY-MM-DD').split('-'))

// 各种 Picker 状态
const showModelPicker = ref(false)
const showDevicePicker = ref(false)
const showWarehousePicker = ref(false)

// 可选项数据
const deviceModels = ref<BookingDeviceModel[]>([])
const availableSlots = ref<BookingCandidate[]>([])
const manualLogisticsByWarehouse = ref<NonNullable<
  BookingAvailabilityPayload['manual_logistics_by_warehouse']
>>({})
let availabilityTimer: ReturnType<typeof setTimeout> | undefined

// 选中名称（显示用）
const selectedModelName = ref('')
const selectedDeviceName = ref('')
const selectedWarehouseName = ref('')

const endDateMin = computed(() => {
  return form.value.startDate ? new Date(form.value.startDate) : undefined
})

// 镜头组合：当前所选机型 short name & 选项
const selectedModelShortName = computed<string | null>(() => {
  if (!form.value.modelId) return null
  const m = deviceModels.value.find(dm => dm.id === form.value.modelId)
  return m?.name ?? null
})
const allowedCombos = computed<LensCombo[]>(() => getAllowedCombos(selectedModelShortName.value))
const lensComboModel = computed<LensCombo>({
  get: () => {
    const v = form.value.lensCombo
    if (v && isComboAllowed(selectedModelShortName.value, v)) return v as LensCombo
    return getDefaultCombo(selectedModelShortName.value)
  },
  set: (v: LensCombo) => { form.value.lensCombo = v }
})
const comboLabel = (v: LensCombo) => lensComboDisplay(v)

// 机型切换 → 重置不合法的镜头组合
watch(selectedModelShortName, (newModel) => {
  if (form.value.lensCombo && !isComboAllowed(newModel, form.value.lensCombo)) {
    form.value.lensCombo = getDefaultCombo(newModel)
  }
})

// Picker 列数据
const modelColumns = computed(() =>
  deviceModels.value.map(m => ({ text: m.display_name || m.name, value: m.id }))
)
const deviceColumns = computed(() =>
  availableSlots.value.map(candidate => ({
    text: `${candidate.device.name} · ${candidate.warehouse.name}`,
    value: candidate.device.id,
  }))
)
const warehouseColumns = computed(() =>
  (booking.bootstrap.value?.warehouses ?? []).map(warehouse => ({
    text: `${warehouse.name} · ${warehouse.address_summary}`,
    value: warehouse.id,
  }))
)
const selectedCandidate = computed(() =>
  booking.availability.value?.candidates.find(
    candidate => candidate.device.id === form.value.deviceId,
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
    return `${type.display_name}（接力确认）`
  }
  if (fact.shortage) return `${type.display_name}（库存不足）`
  return `${type.display_name}（可用 ${fact.available ?? 0}）`
}
const manualLogisticsRequired = computed(() =>
  Object.values(
    booking.availability.value?.estimate_by_warehouse ?? {},
  ).some(estimate => estimate.manual_confirmation_required)
)

// 自动计算发货/入库时间
const shipOutDisplay = computed(() => {
  if (selectedCandidate.value?.planned_ship_out_date) {
    return selectedCandidate.value.planned_ship_out_date
  }
  if (!form.value.startDate) return '—'
  return dayjs(form.value.startDate)
    .subtract(form.value.logisticsDays + 1, 'day')
    .format('YYYY-MM-DD')
})

const shipInDisplay = computed(() => {
  if (selectedCandidate.value?.planned_return_date) {
    return selectedCandidate.value.planned_return_date
  }
  if (!form.value.endDate) return '—'
  return dayjs(form.value.endDate)
    .add(form.value.logisticsDays + 1, 'day')
    .format('YYYY-MM-DD')
})

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

const availabilityInputReady = () => Boolean(
  form.value.startDate
  && form.value.endDate
  && form.value.modelId
  && form.value.customerProvince.trim()
  && form.value.customerCity.trim()
  && form.value.customerDistrict.trim()
  && form.value.customerAddressDetail.trim()
)

const checkAvailability = async () => {
  if (!availabilityInputReady() || !form.value.modelId) {
    booking.resetAvailability()
    availableSlots.value = []
    return
  }
  const priorDeviceId = form.value.deviceId
  try {
    const result = await booking.evaluateAvailability({
      start_date: form.value.startDate,
      end_date: form.value.endDate,
      model_id: form.value.modelId,
      preferred_warehouse_id: form.value.preferredWarehouseId,
      destination: structuredDestination(),
      requested_accessory_type_ids: [
        ...form.value.requestedAccessoryTypeIds,
      ].sort((left, right) => left - right),
      ...(Object.keys(manualLogisticsByWarehouse.value).length
        ? { manual_logistics_by_warehouse: manualLogisticsByWarehouse.value }
        : {}),
    })
    if (!result) return
    availableSlots.value = result.candidates.filter(
      candidate => candidate.available,
    )
    if (!availableSlots.value.some(
      candidate => candidate.device.id === priorDeviceId,
    )) {
      form.value.deviceId = null
      form.value.requestedAccessoryTypeIds = []
      selectedDeviceName.value = ''
    }
    if (!availableSlots.value.length) {
      showToast({ message: '无可用设备', type: 'fail' })
    }
  } catch (e: any) {
    availableSlots.value = []
    form.value.deviceId = null
    selectedDeviceName.value = ''
    showToast({ message: e.message || '查找档期失败', type: 'fail' })
  }
}

const scheduleAvailability = () => {
  if (availabilityTimer) clearTimeout(availabilityTimer)
  availabilityTimer = setTimeout(() => {
    void checkAvailability()
  }, 250)
}

watch([
  () => form.value.startDate,
  () => form.value.endDate,
  () => form.value.modelId,
  () => form.value.preferredWarehouseId,
  () => form.value.customerProvince,
  () => form.value.customerCity,
  () => form.value.customerDistrict,
  () => form.value.customerAddressDetail,
], () => {
  manualLogisticsByWarehouse.value = {}
  scheduleAvailability()
})

watch([
  () => form.value.requestedAccessoryTypeIds.join(','),
], scheduleAvailability)

watch(() => form.value.logisticsDays, () => {
  manualLogisticsByWarehouse.value = {}
  scheduleAvailability()
})

// Picker 确认处理
const onModelConfirm = ({ selectedValues, selectedOptions }: any) => {
  form.value.modelId = selectedValues[0]
  selectedModelName.value = selectedOptions[0]?.text ?? ''
  showModelPicker.value = false
}

const onDeviceConfirm = ({ selectedValues, selectedOptions }: any) => {
  form.value.deviceId = selectedValues[0]
  selectedDeviceName.value = selectedOptions[0]?.text ?? ''
  form.value.requestedAccessoryTypeIds = []
  showDevicePicker.value = false
}

const onWarehouseConfirm = ({ selectedValues, selectedOptions }: any) => {
  form.value.preferredWarehouseId = selectedValues[0]
  selectedWarehouseName.value = selectedOptions[0]?.text ?? ''
  showWarehousePicker.value = false
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
  await checkAvailability()
}

const onStartDateConfirm = ({ selectedValues }: any) => {
  form.value.startDate = selectedValues.join('-')
  startDateParts.value = selectedValues
  showStartDatePicker.value = false
}

const onEndDateConfirm = ({ selectedValues }: any) => {
  form.value.endDate = selectedValues.join('-')
  endDateParts.value = selectedValues
  showEndDatePicker.value = false
}

// 拉取闲鱼订单信息
const fetchOrderInfo = async () => {
  if (!form.value.xianyuOrderNo.trim()) {
    showToast('请输入闲鱼订单号')
    return
  }
  fetchingOrder.value = true
  try {
    const res = await axios.post('/api/rentals/fetch-xianyu-order', {
      order_no: form.value.xianyuOrderNo.trim()
    })
    if (res.data.success) {
      const d = res.data.data
      form.value.customerName = d.buyer_nick || d.receiver_name || form.value.customerName
      form.value.customerPhone = d.receiver_mobile || form.value.customerPhone
      form.value.customerProvince = d.prov_name || form.value.customerProvince
      form.value.customerCity = d.city_name || form.value.customerCity
      form.value.customerDistrict = d.area_name || form.value.customerDistrict
      form.value.customerAddressDetail = [d.town_name, d.address]
        .filter(Boolean)
        .join('') || form.value.customerAddressDetail
      syncLegacyDestination()
      form.value.buyerId = d.buyer_eid || form.value.buyerId
      form.value.orderAmount = d.pay_amount ? String(d.pay_amount / 100) : form.value.orderAmount
      showToast({ message: '订单信息已填充', type: 'success' })
    } else {
      showToast({ message: res.data.error || '拉取失败', type: 'fail' })
    }
  } catch (e: any) {
    showToast({ message: e.message || '网络错误', type: 'fail' })
  } finally {
    fetchingOrder.value = false
  }
}

// 提交
const onSubmit = async () => {
  if (!form.value.deviceId) {
    showToast('请选择可用设备')
    return
  }
  const candidate = selectedCandidate.value
  if (!candidate?.submission_ready) {
    showToast('请先完成物流天数确认')
    return
  }
  syncLegacyDestination()

  // 重复租赁检测
  const { hasDuplicate } = await conflictDetection.checkDuplicateRental({
    customerName: form.value.customerName,
    destination: form.value.destination,
    startDate: form.value.startDate,
    endDate: form.value.endDate
  })

  if (hasDuplicate) {
    try {
      await showConfirmDialog({
        title: '发现重复租赁',
        message: '该客户在相同时间段已有租赁记录，确定要继续创建吗？'
      })
    } catch {
      return
    }
  }

  submitting.value = true
  try {
    const shipTimes = conflictDetection.calculateShipTimes(
      form.value.startDate,
      form.value.endDate,
      form.value.logisticsDays
    )

    const rentalData = {
      device_id: form.value.deviceId,
      model_id: form.value.modelId,
      expected_origin_warehouse_id: candidate.warehouse.id,
      preferred_warehouse_id: form.value.preferredWarehouseId,
      start_date: form.value.startDate,
      end_date: form.value.endDate,
      customer_name: form.value.customerName,
      customer_phone: form.value.customerPhone,
      destination: structuredDestination(),
      legacy_destination: form.value.destination,
      customer_province: form.value.customerProvince.trim(),
      customer_city: form.value.customerCity.trim(),
      customer_district: form.value.customerDistrict.trim(),
      customer_address_detail: form.value.customerAddressDetail.trim(),
      order_amount: form.value.orderAmount ? parseFloat(form.value.orderAmount) : undefined,
      buyer_id: form.value.buyerId || undefined,
      xianyu_order_no: form.value.xianyuOrderNo || undefined,
      logistics_days: form.value.logisticsDays,
      ship_out_time: shipTimes.ship_out_time,
      ship_in_time: shipTimes.ship_in_time,
      includes_handle: form.value.bundledAccessories.includes('handle'),
      includes_lens_mount: form.value.bundledAccessories.includes('lens_mount'),
      photo_transfer: form.value.photoTransfer,
      lens_combo: lensComboModel.value,
      accessories: [],
      requested_accessory_type_ids: [
        ...form.value.requestedAccessoryTypeIds,
      ].sort((left, right) => left - right),
      manual_logistics_by_warehouse: manualLogisticsByWarehouse.value,
    }

    const result = await ganttStore.createRental(rentalData)
    showToast({ message: '租赁创建成功', type: 'success' })
    const rentalId = result?.data?.main_rental?.id
    if (typeof rentalId !== 'number' || !Number.isFinite(rentalId) || rentalId <= 0) {
      showConfirmationLoadFailure()
      return
    }
    let latestRental: Rental | null = null
    try {
      latestRental = await ganttStore.getRentalById(rentalId)
    } catch {
      latestRental = null
    }
    if (!latestRental) {
      showConfirmationLoadFailure()
      return
    }
    savedRental.value = latestRental
  } catch (e: any) {
    showToast({ message: e.message || '创建失败', type: 'fail' })
  } finally {
    submitting.value = false
  }
}

const showConfirmationLoadFailure = () => {
  showToast({
    message: '保存成功，但确认信息加载失败',
    type: 'fail',
    onClose: () => {
      if (route.name === 'create-rental') router.back()
    },
  })
}

const handleConfirmationClosed = () => {
  savedRental.value = null
  router.back()
}

// 一次加载预约页所需的非库存元数据。
const loadInitData = async () => {
  try {
    const result = await booking.loadBootstrap()
    deviceModels.value = result.device_models
    const preferredWarehouseId = (
      result.recent_warehouse_id
      ?? result.default_warehouse_id
      ?? result.warehouses[0]?.id
      ?? null
    )
    form.value.preferredWarehouseId = preferredWarehouseId
    const warehouse = result.warehouses.find(
      item => item.id === preferredWarehouseId,
    )
    selectedWarehouseName.value = warehouse
      ? `${warehouse.name} · ${warehouse.address_summary}`
      : ''
  } catch (e) {
    console.error('加载初始数据失败:', e)
    showToast({ message: '预约表单加载失败，请稍后重试', type: 'fail' })
  }
}

onMounted(async () => {
  await loadInitData()
})

onBeforeUnmount(() => {
  if (availabilityTimer) clearTimeout(availabilityTimer)
  booking.resetAvailability()
})
</script>

<style scoped>
.form-view {
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: #f7f8fa;
}

.form-scroll {
  flex: 1;
  overflow-y: auto;
  -webkit-overflow-scrolling: touch;
  padding-bottom: 24px;
}

.submit-wrap {
  padding: 16px;
}

.combo-radio-group {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  width: 100%;
}
.combo-chip {
  cursor: pointer;
  padding: 4px 10px;
}
</style>
