<template>
  <div class="edit-rental-page">
    <van-nav-bar
      title="编辑租赁"
      left-text="返回"
      left-arrow
      fixed
      placeholder
      @click-left="router.back()"
    />

    <div v-if="initialLoading" class="loading-center">
      <van-loading color="#409eff" />
    </div>

    <van-form v-else @submit="onSubmit">
      <van-cell-group inset title="预约与客户">
        <van-field
          v-model="form.customerName"
          label="闲鱼 ID"
          required
          maxlength="100"
        />
        <van-field
          v-model="form.customerPhone"
          label="客户电话"
          type="tel"
          maxlength="20"
        />
        <van-field
          :model-value="selectedModelName"
          label="设备型号"
          readonly
          clickable
          required
          @click="showModelPicker = true"
        />
        <van-field
          :model-value="selectedDeviceName"
          label="主设备"
          readonly
          clickable
          required
          @click="showDevicePicker = true"
        />
        <van-field
          :model-value="selectedWarehouseName"
          label="优先仓库"
          readonly
          clickable
          @click="showWarehousePicker = true"
        />
        <van-field v-model="form.startDate" label="开始日期" type="date" required />
        <van-field v-model="form.endDate" label="结束日期" type="date" required />
      </van-cell-group>

      <van-cell-group inset title="结构化收货地址" class="section">
        <van-field v-model="form.customerProvince" label="省" required maxlength="50" />
        <van-field v-model="form.customerCity" label="市" required maxlength="50" />
        <van-field v-model="form.customerDistrict" label="区县" required maxlength="50" />
        <van-field
          v-model="form.customerAddressDetail"
          label="详细地址"
          type="textarea"
          rows="2"
          autosize
          required
          maxlength="255"
        />
      </van-cell-group>

      <van-cell-group inset title="订单与配件" class="section">
        <van-field v-model="form.xianyuOrderNo" label="闲鱼订单号" maxlength="50" />
        <van-field v-model="form.orderAmount" label="订单金额" type="number" />
        <van-field v-model="form.buyerId" label="买家 ID" maxlength="100" />
        <van-field label="随机配件">
          <template #input>
            <van-checkbox-group v-model="form.bundledAccessories" direction="horizontal">
              <van-checkbox name="handle" shape="square">手柄</van-checkbox>
              <van-checkbox name="lens_mount" shape="square" class="inline-check">镜头座</van-checkbox>
            </van-checkbox-group>
          </template>
        </van-field>
        <van-field label="逻辑附件">
          <template #input>
            <van-checkbox-group v-model="form.requestedAccessoryTypeIds">
              <van-checkbox
                v-for="accessory in logicalAccessoryTypes"
                :key="accessory.id"
                :name="accessory.id"
                shape="square"
                class="logical-check"
              >{{ accessory.display_name || accessory.name }}</van-checkbox>
            </van-checkbox-group>
          </template>
        </van-field>
        <van-field label="镜头组合">
          <template #input>
            <div class="combo-row">
              <van-tag
                v-for="combo in lensCombos"
                :key="combo.value"
                :type="form.lensCombo === combo.value ? 'primary' : 'default'"
                :plain="form.lensCombo !== combo.value"
                size="medium"
                @click="form.lensCombo = combo.value"
              >{{ combo.label }}</van-tag>
            </div>
          </template>
        </van-field>
        <van-field label="代传照片">
          <template #input>
            <van-switch v-model="form.photoTransfer" size="20" />
          </template>
        </van-field>
      </van-cell-group>

      <van-cell-group inset title="物流与库存复验" class="section">
        <van-notice-bar
          v-if="booking.availabilityFailed.value"
          text="无法确认当前档期和物流，请稍后重试"
          color="#ee0a24"
          background="#fff0f0"
          wrapable
        />
        <van-notice-bar
          v-else-if="selectedCandidate && !selectedCandidate.available"
          text="所选设备与当前使用期冲突"
          color="#ee0a24"
          background="#fff0f0"
        />
        <van-notice-bar
          v-else-if="selectedCandidate?.submission_ready"
          :text="`可提交：${selectedCandidate.planned_ship_out_date} 寄出，${selectedCandidate.planned_return_date} 回仓`"
          color="#07c160"
          background="#f0fff5"
          wrapable
        />
        <van-cell
          v-for="estimate in manualEstimates"
          :key="estimate.warehouse_id"
          :title="`${warehouseName(estimate.warehouse_id)}物流时效`"
        >
          <template #value>
            <div class="manual-row">
              <van-stepper
                v-model="manualDays[estimate.warehouse_id]"
                :min="0"
                :max="7"
                integer
              />
              <van-button
                size="small"
                type="primary"
                plain
                @click="confirmManualLogistics(estimate.warehouse_id)"
              >确认</van-button>
            </div>
          </template>
        </van-cell>
      </van-cell-group>

      <van-cell-group inset title="损坏反馈" class="section">
        <van-notice-bar
          v-if="form.damageNote.trim()"
          text="已记录用户损坏反馈，验货时将重点提示"
          color="#ee0a24"
          background="#fff0f0"
          wrapable
        />
        <van-field
          v-model="form.damageNote"
          label="损坏备注"
          type="textarea"
          rows="3"
          autosize
          maxlength="1000"
          show-word-limit
        />
        <van-cell title="当前状态" :value="currentRental?.status || '-'" />
        <van-notice-bar
          text="状态、运单和实际收发时间由对应作业动作维护。"
          wrapable
        />
      </van-cell-group>

      <div class="actions">
        <van-button
          type="primary"
          block
          native-type="submit"
          :loading="submitting"
          :disabled="!canSubmit"
        >保存修改</van-button>
        <van-button
          type="danger"
          plain
          block
          :disabled="submitting"
          @click="deleteRental"
        >删除租赁</van-button>
      </div>
    </van-form>

    <van-popup v-model:show="showModelPicker" position="bottom" round>
      <van-picker
        title="选择设备型号"
        show-toolbar
        :columns="modelColumns"
        @confirm="onModelConfirm"
        @cancel="showModelPicker = false"
      />
    </van-popup>
    <van-popup v-model:show="showDevicePicker" position="bottom" round>
      <van-picker
        title="选择主设备"
        show-toolbar
        :columns="deviceColumns"
        @confirm="onDeviceConfirm"
        @cancel="showDevicePicker = false"
      />
    </van-popup>
    <van-popup v-model:show="showWarehousePicker" position="bottom" round>
      <van-picker
        title="选择优先仓库"
        show-toolbar
        :columns="warehouseColumns"
        @confirm="onWarehouseConfirm"
        @cancel="showWarehousePicker = false"
      />
    </van-popup>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { showConfirmDialog, showToast } from 'vant'
import dayjs from 'dayjs'

import {
  useGanttStore,
  type Rental,
  type RentalEditContext,
} from '@/stores/gantt'
import {
  useRentalBooking,
  type BookingCandidate,
} from '@/composables/useRentalBooking'

const route = useRoute()
const router = useRouter()
const ganttStore = useGanttStore()
const booking = useRentalBooking()
const rentalId = computed(() => Number(route.params.id))
const editContext = ref<RentalEditContext | null>(null)
const currentRental = ref<Rental | null>(null)
const initialLoading = ref(true)
const submitting = ref(false)
const showModelPicker = ref(false)
const showDevicePicker = ref(false)
const showWarehousePicker = ref(false)
const manualDays = reactive<Record<number, number>>({})
const manualConfirmations = reactive<Record<string, { days: number; context: string }>>({})
let availabilityTimer: ReturnType<typeof setTimeout> | undefined
let initialScheduleKey = ''
let seededExistingLogistics = false

const form = reactive({
  customerName: '',
  customerPhone: '',
  modelId: null as number | null,
  deviceId: null as number | null,
  preferredWarehouseId: null as number | null,
  startDate: '',
  endDate: '',
  customerProvince: '',
  customerCity: '',
  customerDistrict: '',
  customerAddressDetail: '',
  requestedAccessoryTypeIds: [] as number[],
  bundledAccessories: [] as Array<'handle' | 'lens_mount'>,
  xianyuOrderNo: '',
  orderAmount: '',
  buyerId: '',
  damageNote: '',
  photoTransfer: false,
  lensCombo: 'lens_400mm' as 'lens_400mm' | 'lens_200mm' | 'bare' | 'lens_dual',
})

const lensCombos = [
  { value: 'lens_400mm' as const, label: '400MM' },
  { value: 'lens_200mm' as const, label: '200MM' },
  { value: 'bare' as const, label: '裸机' },
  { value: 'lens_dual' as const, label: '双镜头' },
]

const logicalAccessoryTypes = computed(() =>
  (editContext.value?.accessory_types || []).filter(
    accessory => accessory.tracking_mode === 'logical_unit',
  ),
)

const selectedCandidate = computed(() =>
  booking.availability.value?.candidates.find(
    candidate => candidate.device.id === form.deviceId,
  ) || null,
)

const manualEstimates = computed(() =>
  Object.values(booking.availability.value?.estimate_by_warehouse || {})
    .filter(estimate => estimate.manual_confirmation_required),
)

const formReady = computed(() => Boolean(
  editContext.value
  && form.customerName.trim()
  && form.modelId
  && form.deviceId
  && form.startDate
  && form.endDate
  && !dayjs(form.endDate).isBefore(dayjs(form.startDate), 'day')
  && form.customerProvince.trim()
  && form.customerCity.trim()
  && form.customerDistrict.trim()
  && form.customerAddressDetail.trim(),
))

const canSubmit = computed(() => Boolean(
  formReady.value
  && !booking.availabilityLoading.value
  && !booking.availabilityFailed.value
  && selectedCandidate.value?.available
  && selectedCandidate.value?.submission_ready,
))

const selectedModelName = computed(() => {
  const model = editContext.value?.device_models.find(item => item.id === form.modelId)
  return model?.display_name || model?.name || '请选择'
})

const selectedDeviceName = computed(() => {
  const candidate = selectedCandidate.value
  if (candidate) return deviceLabel(candidate)
  const device = editContext.value?.devices.find(item => item.id === form.deviceId)
  return device?.name || '请选择'
})

const selectedWarehouseName = computed(() =>
  warehouseName(form.preferredWarehouseId) || '不指定',
)

const modelColumns = computed(() =>
  (editContext.value?.device_models || []).map(model => ({
    text: model.display_name || model.name,
    value: model.id,
  })),
)

const deviceColumns = computed(() =>
  (booking.availability.value?.candidates || []).map(candidate => ({
    text: deviceLabel(candidate),
    value: candidate.device.id,
    disabled: !candidate.available,
  })),
)

const warehouseColumns = computed(() => [
  { text: '不指定', value: null },
  ...(editContext.value?.warehouses || []).map(warehouse => ({
    text: warehouse.name,
    value: warehouse.id,
  })),
])

const warehouseName = (id: number | null | undefined) =>
  editContext.value?.warehouses.find(warehouse => warehouse.id === id)?.name || ''

const deviceLabel = (candidate: BookingCandidate) => {
  const state = candidate.available ? '' : '（档期冲突）'
  return `${candidate.device.name} / ${candidate.warehouse.name}${state}`
}

const scheduleKey = () => JSON.stringify({
  modelId: form.modelId,
  deviceId: form.deviceId,
  preferredWarehouseId: form.preferredWarehouseId,
  startDate: form.startDate,
  endDate: form.endDate,
  province: form.customerProvince.trim(),
  city: form.customerCity.trim(),
  district: form.customerDistrict.trim(),
  addressDetail: form.customerAddressDetail.trim(),
  accessoryTypes: [...form.requestedAccessoryTypeIds].sort((a, b) => a - b),
})

const buildAvailabilityPayload = () => ({
  start_date: form.startDate,
  end_date: form.endDate,
  model_id: form.modelId!,
  preferred_warehouse_id: form.preferredWarehouseId,
  exclude_rental_id: rentalId.value,
  destination: {
    province: form.customerProvince.trim(),
    city: form.customerCity.trim(),
    district: form.customerDistrict.trim(),
    address_detail: form.customerAddressDetail.trim(),
  },
  requested_accessory_type_ids: [...form.requestedAccessoryTypeIds],
  manual_logistics_by_warehouse: { ...manualConfirmations },
})

const evaluateAvailability = async () => {
  if (!formReady.value) {
    booking.resetAvailability()
    return
  }
  try {
    const result = await booking.evaluateAvailability(buildAvailabilityPayload())
    if (!result || seededExistingLogistics || scheduleKey() !== initialScheduleKey) return
    const rental = currentRental.value
    const candidate = result.candidates.find(item => item.device.id === form.deviceId)
    const estimate = candidate
      ? result.estimate_by_warehouse[String(candidate.warehouse.id)]
      : null
    if (
      candidate
      && estimate?.manual_confirmation_required
      && rental?.logistics_days != null
      && rental.logistics_estimate_origin_warehouse_id === candidate.warehouse.id
    ) {
      seededExistingLogistics = true
      manualDays[candidate.warehouse.id] = Number(rental.logistics_days)
      manualConfirmations[String(candidate.warehouse.id)] = {
        days: Number(rental.logistics_days),
        context: estimate.confirmation_context,
      }
      await booking.evaluateAvailability(buildAvailabilityPayload())
    }
  } catch {
    // Fail-closed state is owned by the booking composable.
  }
}

const queueAvailability = () => {
  if (availabilityTimer) clearTimeout(availabilityTimer)
  availabilityTimer = setTimeout(() => void evaluateAvailability(), 300)
}

const confirmManualLogistics = async (warehouseId: number) => {
  const estimate = booking.availability.value?.estimate_by_warehouse[String(warehouseId)]
  const days = manualDays[warehouseId]
  if (!estimate || !Number.isInteger(days) || days < 0 || days > 7) {
    showToast('请填写 0–7 天的物流时效')
    return
  }
  manualConfirmations[String(warehouseId)] = {
    days,
    context: estimate.confirmation_context,
  }
  await evaluateAvailability()
}

const load = async () => {
  initialLoading.value = true
  try {
    const context = await ganttStore.getRentalEditContext(rentalId.value)
    if (!context) throw new Error('编辑上下文不可用')
    editContext.value = context
    currentRental.value = context.rental
    const rental = context.rental
    const device = context.devices.find(item => item.id === rental.device_id)
    form.customerName = rental.customer_name || ''
    form.customerPhone = rental.customer_phone || ''
    form.modelId = rental.device?.model_id || device?.model_id || null
    form.deviceId = rental.device_id
    form.preferredWarehouseId = rental.preferred_warehouse_id
      ?? device?.warehouse_id
      ?? null
    form.startDate = rental.start_date || ''
    form.endDate = rental.end_date || ''
    form.customerProvince = rental.customer_province || ''
    form.customerCity = rental.customer_city || ''
    form.customerDistrict = rental.customer_district || ''
    form.customerAddressDetail = rental.customer_address_detail || ''
    form.requestedAccessoryTypeIds = [...(rental.requested_accessory_type_ids || [])]
    form.bundledAccessories = []
    if (rental.includes_handle) form.bundledAccessories.push('handle')
    if (rental.includes_lens_mount) form.bundledAccessories.push('lens_mount')
    form.xianyuOrderNo = rental.xianyu_order_no || ''
    form.orderAmount = rental.order_amount == null ? '' : String(rental.order_amount)
    form.buyerId = rental.buyer_id || ''
    form.damageNote = rental.damage_note || ''
    form.photoTransfer = Boolean(rental.photo_transfer)
    form.lensCombo = rental.lens_combo || 'lens_400mm'
    initialScheduleKey = scheduleKey()
    await evaluateAvailability()
  } catch (error: any) {
    showToast({ message: error?.message || '加载失败', type: 'fail' })
  } finally {
    initialLoading.value = false
  }
}

const onSubmit = async () => {
  if (!canSubmit.value || !selectedCandidate.value) {
    showToast({ message: '请先完成档期、物流和附件复验', type: 'fail' })
    return
  }
  submitting.value = true
  try {
    await ganttStore.updateRental(rentalId.value, {
      ...buildAvailabilityPayload(),
      device_id: form.deviceId,
      expected_origin_warehouse_id: selectedCandidate.value.warehouse.id,
      customer_name: form.customerName.trim(),
      customer_phone: form.customerPhone.trim() || null,
      legacy_destination: [
        form.customerProvince,
        form.customerCity,
        form.customerDistrict,
        form.customerAddressDetail,
      ].join(''),
      xianyu_order_no: form.xianyuOrderNo.trim() || null,
      order_amount: form.orderAmount === '' ? null : form.orderAmount,
      buyer_id: form.buyerId.trim() || null,
      includes_handle: form.bundledAccessories.includes('handle'),
      includes_lens_mount: form.bundledAccessories.includes('lens_mount'),
      photo_transfer: form.photoTransfer,
      lens_combo: form.lensCombo,
      damage_note: form.damageNote.trim() || null,
    })
    showToast({ message: '保存成功', type: 'success' })
    router.back()
  } catch (error: any) {
    showToast({
      message: error?.response?.data?.message || error?.message || '保存失败',
      type: 'fail',
    })
  } finally {
    submitting.value = false
  }
}

const deleteRental = async () => {
  try {
    await showConfirmDialog({ title: '删除确认', message: '确定删除这条租赁记录吗？' })
    submitting.value = true
    await ganttStore.deleteRental(rentalId.value)
    showToast({ message: '删除成功', type: 'success' })
    router.back()
  } catch (error: any) {
    if (error !== 'cancel') {
      showToast({ message: error?.message || '删除失败', type: 'fail' })
    }
  } finally {
    submitting.value = false
  }
}

const onModelConfirm = ({ selectedValues }: any) => {
  const nextModelId = selectedValues[0]
  if (nextModelId !== form.modelId) {
    form.modelId = nextModelId
    form.deviceId = null
  }
  showModelPicker.value = false
}

const onDeviceConfirm = ({ selectedValues }: any) => {
  form.deviceId = selectedValues[0]
  showDevicePicker.value = false
}

const onWarehouseConfirm = ({ selectedValues }: any) => {
  form.preferredWarehouseId = selectedValues[0] ?? null
  showWarehousePicker.value = false
}

watch(
  () => scheduleKey(),
  () => {
    if (!editContext.value) return
    if (scheduleKey() !== initialScheduleKey) {
      for (const key of Object.keys(manualConfirmations)) delete manualConfirmations[key]
    }
    queueAvailability()
  },
)

onMounted(() => void load())

onBeforeUnmount(() => {
  if (availabilityTimer) clearTimeout(availabilityTimer)
  booking.resetAvailability()
})
</script>

<style scoped>
.edit-rental-page {
  min-height: 100vh;
  padding-bottom: 24px;
  background: #f7f8fa;
}

.loading-center {
  display: flex;
  justify-content: center;
  padding-top: 120px;
}

.section {
  margin-top: 12px;
}

.inline-check {
  margin-left: 12px;
}

.logical-check + .logical-check {
  margin-top: 8px;
}

.combo-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.manual-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.actions {
  display: grid;
  gap: 10px;
  margin: 18px 16px 0;
}
</style>
