<template>
  <el-dialog
    v-model="dialogVisible"
    title="编辑租赁记录"
    width="680px"
    :close-on-click-modal="false"
    :close-on-press-escape="!submitting"
    :show-close="!submitting"
    @closed="handleClosed"
  >
    <RentalActionButtons
      :rental="rental"
      :loading-latest-data="loadingLatestData"
      :latest-data-error="latestDataError"
      :submitting="submitting"
      @open-contract="openContract"
      @open-shipping-order="openShippingOrder"
      @delete="handleDelete"
      @ship-to-xianyu="handleShipToXianyu"
    />

    <el-form v-if="rental" ref="formRef" :model="form" label-width="118px">
      <el-divider content-position="left">预约与客户</el-divider>
      <el-form-item label="闲鱼 ID" required>
        <el-input v-model="form.customerName" maxlength="100" />
      </el-form-item>
      <el-form-item label="客户电话">
        <el-input v-model="form.customerPhone" maxlength="20" />
      </el-form-item>
      <el-form-item label="设备型号" required>
        <el-select v-model="form.modelId" style="width: 100%">
          <el-option
            v-for="model in editContext?.device_models || []"
            :key="model.id"
            :label="model.display_name || model.name"
            :value="model.id"
          />
        </el-select>
      </el-form-item>
      <el-form-item label="主设备" required>
        <el-select
          v-model="form.deviceId"
          :loading="booking.availabilityLoading.value"
          style="width: 100%"
        >
          <el-option
            v-for="candidate in deviceCandidates"
            :key="candidate.device.id"
            :label="deviceLabel(candidate)"
            :value="candidate.device.id"
            :disabled="!candidate.available"
          />
        </el-select>
      </el-form-item>
      <el-form-item label="优先仓库">
        <el-select v-model="form.preferredWarehouseId" clearable style="width: 100%">
          <el-option
            v-for="warehouse in editContext?.warehouses || []"
            :key="warehouse.id"
            :label="warehouse.name"
            :value="warehouse.id"
          />
        </el-select>
      </el-form-item>
      <el-form-item label="开始日期" required>
        <el-date-picker
          v-model="form.startDate"
          type="date"
          value-format="YYYY-MM-DD"
          style="width: 100%"
        />
      </el-form-item>
      <el-form-item label="结束日期" required>
        <el-date-picker
          v-model="form.endDate"
          type="date"
          value-format="YYYY-MM-DD"
          :disabled-date="disableEndDate"
          style="width: 100%"
        />
      </el-form-item>

      <el-divider content-position="left">结构化收货地址</el-divider>
      <div class="address-grid">
        <el-form-item label="省" required>
          <el-input v-model="form.customerProvince" maxlength="50" />
        </el-form-item>
        <el-form-item label="市" required>
          <el-input v-model="form.customerCity" maxlength="50" />
        </el-form-item>
        <el-form-item label="区县" required>
          <el-input v-model="form.customerDistrict" maxlength="50" />
        </el-form-item>
      </div>
      <el-form-item label="详细地址" required>
        <el-input
          v-model="form.customerAddressDetail"
          type="textarea"
          :rows="2"
          maxlength="255"
        />
      </el-form-item>

      <el-divider content-position="left">订单与配件</el-divider>
      <el-form-item label="闲鱼订单号">
        <el-input v-model="form.xianyuOrderNo" maxlength="50" />
      </el-form-item>
      <el-form-item label="订单金额">
        <el-input v-model="form.orderAmount" type="number" />
      </el-form-item>
      <el-form-item label="买家 ID">
        <el-input v-model="form.buyerId" maxlength="100" />
      </el-form-item>
      <el-form-item label="随机配件">
        <el-checkbox-group v-model="form.bundledAccessories">
          <el-checkbox value="handle">手柄</el-checkbox>
          <el-checkbox value="lens_mount">镜头座</el-checkbox>
        </el-checkbox-group>
      </el-form-item>
      <el-form-item label="逻辑附件">
        <el-checkbox-group v-model="form.requestedAccessoryTypeIds">
          <el-checkbox
            v-for="accessory in logicalAccessoryTypes"
            :key="accessory.id"
            :value="accessory.id"
          >
            {{ accessory.display_name || accessory.name }}
          </el-checkbox>
        </el-checkbox-group>
        <div class="form-tip">只选择附件类型，系统在最终事务分配内部逻辑单元。</div>
      </el-form-item>
      <el-form-item label="镜头组合">
        <el-select v-model="form.lensCombo" style="width: 100%">
          <el-option label="400MM 镜头" value="lens_400mm" />
          <el-option label="200MM 镜头" value="lens_200mm" />
          <el-option label="裸机" value="bare" />
          <el-option label="双镜头" value="lens_dual" />
        </el-select>
      </el-form-item>
      <el-form-item label="代传照片">
        <el-switch v-model="form.photoTransfer" />
      </el-form-item>

      <el-divider content-position="left">物流复验</el-divider>
      <el-alert
        v-if="booking.availabilityFailed.value"
        title="无法确认当前档期和物流，请稍后重试"
        type="error"
        :closable="false"
        show-icon
      />
      <el-alert
        v-else-if="selectedCandidate && !selectedCandidate.available"
        title="所选设备与当前使用期冲突"
        type="error"
        :closable="false"
        show-icon
      />
      <el-alert
        v-else-if="selectedCandidate?.submission_ready"
        :title="`最终复验可提交；计划寄出 ${selectedCandidate.planned_ship_out_date}，计划回仓 ${selectedCandidate.planned_return_date}`"
        type="success"
        :closable="false"
        show-icon
      />
      <template v-for="estimate in manualEstimates" :key="estimate.warehouse_id">
        <el-form-item :label="`${warehouseName(estimate.warehouse_id)}时效`">
          <el-input-number
            v-model="manualDays[estimate.warehouse_id]"
            :min="0"
            :max="7"
          />
          <el-button
            type="primary"
            plain
            class="manual-confirm"
            @click="confirmManualLogistics(estimate.warehouse_id)"
          >确认并复验</el-button>
        </el-form-item>
      </template>

      <el-divider content-position="left">损坏反馈</el-divider>
      <el-alert
        v-if="form.damageNote.trim()"
        class="damage-note-warning"
        title="已记录用户损坏反馈，验货时将重点提示"
        type="error"
        :closable="false"
        show-icon
      />
      <el-form-item label="损坏备注">
        <el-input
          v-model="form.damageNote"
          class="damage-note-input"
          type="textarea"
          :rows="3"
          maxlength="1000"
          show-word-limit
        />
      </el-form-item>
      <el-alert
        :title="`当前状态：${rental.status}。状态、运单和实际收发时间由对应作业动作维护。`"
        type="info"
        :closable="false"
      />
    </el-form>

    <template #footer>
      <el-button :disabled="submitting" @click="handleClose">取消</el-button>
      <el-button
        type="primary"
        :loading="submitting"
        :disabled="!canSubmit"
        @click="handleSubmit"
      >保存</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox, type FormInstance } from 'element-plus'
import { useRouter } from 'vue-router'
import dayjs from 'dayjs'

import RentalActionButtons from './RentalActionButtons.vue'
import { useGanttStore, type Rental, type RentalEditContext } from '@/stores/gantt'
import {
  useRentalBooking,
  type BookingCandidate,
} from '@/composables/useRentalBooking'

interface Props {
  modelValue: boolean
  rental: Rental | null
}

const props = defineProps<Props>()
const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  'success': [rentalId?: number]
}>()

const ganttStore = useGanttStore()
const router = useRouter()
const booking = useRentalBooking()
const formRef = ref<FormInstance>()
const editContext = ref<RentalEditContext | null>(null)
const loadingLatestData = ref(false)
const latestDataError = ref<string | null>(null)
const submitting = ref(false)
const pendingSuccess = ref<{ rentalId?: number } | null>(null)
const dialogClosed = ref(!props.modelValue)
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

const dialogVisible = computed({
  get: () => props.modelValue,
  set: value => emit('update:modelValue', value),
})

const logicalAccessoryTypes = computed(() =>
  (editContext.value?.accessory_types || []).filter(
    accessory => accessory.tracking_mode === 'logical_unit',
  ),
)

const warehouseById = (id: number | null | undefined) =>
  (editContext.value?.warehouses || []).find(warehouse => warehouse.id === id)

const deviceCandidates = computed(() => {
  return booking.availability.value?.candidates || []
})

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
  && !loadingLatestData.value
  && !booking.availabilityLoading.value
  && !booking.availabilityFailed.value
  && selectedCandidate.value?.available
  && selectedCandidate.value?.submission_ready,
))

const warehouseName = (id: number) => warehouseById(id)?.name || `仓库 ${id}`

const deviceLabel = (candidate: BookingCandidate) => {
  const serial = candidate.device.serial_number
    ? ` / ${candidate.device.serial_number}`
    : ''
  const conflict = candidate.available ? '' : ' / 档期冲突'
  return `${candidate.device.name} / ${candidate.warehouse?.name || '未知仓'}${serial}${conflict}`
}

const disableEndDate = (value: Date) => (
  Boolean(form.startDate) && dayjs(value).isBefore(dayjs(form.startDate), 'day')
)

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
  exclude_rental_id: props.rental!.id,
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
  if (!formReady.value || !props.rental) {
    booking.resetAvailability()
    return
  }
  try {
    const result = await booking.evaluateAvailability(buildAvailabilityPayload())
    if (!result || seededExistingLogistics || scheduleKey() !== initialScheduleKey) return
    const rentalData = editContext.value?.rental as any
    const candidate = result.candidates.find(item => item.device.id === form.deviceId)
    const estimate = candidate
      ? result.estimate_by_warehouse[String(candidate.warehouse.id)]
      : null
    if (
      candidate
      && estimate?.manual_confirmation_required
      && rentalData?.logistics_days != null
      && rentalData?.logistics_estimate_origin_warehouse_id === candidate.warehouse.id
    ) {
      seededExistingLogistics = true
      manualDays[candidate.warehouse.id] = Number(rentalData.logistics_days)
      manualConfirmations[String(candidate.warehouse.id)] = {
        days: Number(rentalData.logistics_days),
        context: estimate.confirmation_context,
      }
      await booking.evaluateAvailability(buildAvailabilityPayload())
    }
  } catch {
    // The composable clears stale data and marks this request failed.
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
    ElMessage.warning('请填写 0–7 天的物流时效')
    return
  }
  manualConfirmations[String(warehouseId)] = {
    days,
    context: estimate.confirmation_context,
  }
  await evaluateAvailability()
}

const loadEditContext = async () => {
  if (!props.rental) return
  loadingLatestData.value = true
  latestDataError.value = null
  booking.resetAvailability()
  seededExistingLogistics = false
  for (const key of Object.keys(manualConfirmations)) delete manualConfirmations[key]
  try {
    const context = await ganttStore.getRentalEditContext(props.rental.id)
    if (!context) throw new Error('编辑上下文不可用')
    editContext.value = context
    const rental = context.rental as any
    const device = context.devices.find(item => item.id === rental.device_id)
    form.customerName = rental.customer_name || ''
    form.customerPhone = rental.customer_phone || ''
    form.modelId = rental.device?.model_id || device?.model_id || null
    form.deviceId = rental.device_id
    form.preferredWarehouseId = rental.preferred_warehouse_id
      ?? (device as any)?.warehouse_id
      ?? null
    form.startDate = rental.start_date || ''
    form.endDate = rental.end_date || ''
    form.customerProvince = rental.customer_province || ''
    form.customerCity = rental.customer_city || ''
    form.customerDistrict = rental.customer_district || ''
    form.customerAddressDetail = rental.customer_address_detail || ''
    form.requestedAccessoryTypeIds = [
      ...(rental.requested_accessory_type_ids || []),
    ]
    form.bundledAccessories = []
    if (rental.includes_handle) form.bundledAccessories.push('handle')
    if (rental.includes_lens_mount) form.bundledAccessories.push('lens_mount')
    form.xianyuOrderNo = rental.xianyu_order_no || ''
    form.orderAmount = rental.order_amount == null ? '' : String(rental.order_amount)
    form.buyerId = rental.buyer_id || ''
    form.damageNote = rental.damage_note || ''
    form.photoTransfer = Boolean(rental.photo_transfer)
    form.lensCombo = rental.lens_combo || 'lens_400mm'
    Object.assign(props.rental, rental)
    initialScheduleKey = scheduleKey()
    await evaluateAvailability()
  } catch (error: any) {
    latestDataError.value = error?.message || '加载编辑信息失败'
    ElMessage.error(latestDataError.value || '加载编辑信息失败')
  } finally {
    loadingLatestData.value = false
  }
}

const handleSubmit = async () => {
  if (!canSubmit.value || !props.rental || !selectedCandidate.value) {
    ElMessage.error('请先完成当前档期、仓库、物流和附件复验')
    return
  }
  submitting.value = true
  try {
    await ganttStore.updateRental(props.rental.id, {
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
    ElMessage.success('租赁记录更新成功')
    queuePendingSuccess({ rentalId: props.rental.id })
  } catch (error: any) {
    ElMessage.error(`更新失败：${error?.message || '未知错误'}`)
  } finally {
    submitting.value = false
  }
}

const handleClose = () => {
  dialogVisible.value = false
}

const handleClosed = () => {
  dialogClosed.value = true
  flushPendingSuccess()
}

const flushPendingSuccess = () => {
  if (!dialogClosed.value || !pendingSuccess.value) return
  const success = pendingSuccess.value
  pendingSuccess.value = null
  if (typeof success.rentalId === 'number') emit('success', success.rentalId)
  else emit('success')
}

const queuePendingSuccess = (success: { rentalId?: number }) => {
  pendingSuccess.value = success
  if (dialogClosed.value) flushPendingSuccess()
  else handleClose()
}

const handleDelete = async () => {
  if (!props.rental) return
  try {
    await ElMessageBox.confirm('确定删除这条租赁记录吗？', '删除确认', {
      type: 'warning',
      confirmButtonText: '确定删除',
      cancelButtonText: '取消',
    })
    submitting.value = true
    await ganttStore.deleteRental(props.rental.id)
    ElMessage.success('租赁记录删除成功')
    queuePendingSuccess({})
  } catch (error: any) {
    if (error !== 'cancel') ElMessage.error(`删除失败：${error?.message || '未知错误'}`)
  } finally {
    submitting.value = false
  }
}

const handleShipToXianyu = async () => {
  if (!props.rental) return
  try {
    submitting.value = true
    await ganttStore.shipRentalToXianyu(props.rental.id)
    ElMessage.success('已成功发货到闲鱼')
    await loadEditContext()
  } catch (error: any) {
    ElMessage.error(`发货失败：${error?.message || '未知错误'}`)
  } finally {
    submitting.value = false
  }
}

const openContract = () => {
  if (!props.rental) return
  window.open(router.resolve({ path: `/contract/${props.rental.id}` }).href, '_blank')
}

const openShippingOrder = () => {
  if (!props.rental) return
  window.open(router.resolve({ path: `/shipping/${props.rental.id}` }).href, '_blank')
}

watch(
  [() => props.modelValue, () => props.rental?.id],
  ([visible, rentalId], [wasVisible, previousRentalId] = [false, undefined]) => {
    if (!visible || rentalId == null) return
    dialogClosed.value = false
    pendingSuccess.value = null
    if (!wasVisible || rentalId !== previousRentalId) void loadEditContext()
  },
  { immediate: true },
)

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

onBeforeUnmount(() => {
  if (availabilityTimer) clearTimeout(availabilityTimer)
  booking.resetAvailability()
})
</script>

<style scoped>
.address-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
}

.address-grid :deep(.el-form-item) {
  display: block;
}

.form-tip {
  width: 100%;
  margin-top: 4px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.manual-confirm {
  margin-left: 12px;
}

.damage-note-warning {
  margin-bottom: 16px;
}

:deep(.el-alert) {
  margin-bottom: 12px;
}
</style>
