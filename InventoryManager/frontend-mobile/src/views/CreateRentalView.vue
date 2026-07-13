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
            v-model="form.destination"
            label="收货地址"
            placeholder="请输入"
            type="textarea"
            rows="2"
            autosize
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
            v-model="selectedPhoneHolderName"
            readonly
            clickable
            label="手机支架"
            placeholder="无"
            @click="showPhoneHolderPicker = true"
          />

          <van-field
            v-model="selectedTripodName"
            readonly
            clickable
            label="三脚架"
            placeholder="无"
            @click="showTripodPicker = true"
          />

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

    <!-- 手机支架选择器 -->
    <van-popup v-model:show="showPhoneHolderPicker" position="bottom" round>
      <van-picker
        :columns="phoneHolderColumns"
        @confirm="onPhoneHolderConfirm"
        @cancel="showPhoneHolderPicker = false"
        show-toolbar
        title="选择手机支架"
      />
    </van-popup>

    <!-- 三脚架选择器 -->
    <van-popup v-model:show="showTripodPicker" position="bottom" round>
      <van-picker
        :columns="tripodColumns"
        @confirm="onTripodConfirm"
        @cancel="showTripodPicker = false"
        show-toolbar
        title="选择三脚架"
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
import { ref, computed, watch, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { showToast, showConfirmDialog } from 'vant'
import axios from 'axios'
import dayjs from 'dayjs'
import { useGanttStore } from '@/stores/gantt'
import type { DeviceModel, Device, Rental } from '@/stores/gantt'
import RentalConfirmationPopup from '@/components/RentalConfirmationPopup.vue'
import { extractPhoneNumber } from '@/utils/phoneExtractor'
import { useConflictDetection } from '@/composables/useConflictDetection'
import {
  getAllowedCombos,
  getDefaultCombo,
  isComboAllowed,
  lensComboDisplay,
  type LensCombo,
} from '@/config/lensCombo'

const router = useRouter()
const ganttStore = useGanttStore()
const conflictDetection = useConflictDetection()

// 表单状态
const form = ref({
  xianyuOrderNo: '',
  customerName: '',
  customerPhone: '',
  destination: '',
  orderAmount: '',
  buyerId: '',
  modelId: null as number | null,
  deviceId: null as number | null,
  startDate: '',
  endDate: '',
  logisticsDays: 1,
  bundledAccessories: [] as string[],
  phoneHolderId: null as number | null,
  tripodId: null as number | null,
  photoTransfer: false,
  lensCombo: undefined as ('lens_400mm' | 'lens_200mm' | 'bare' | 'lens_dual' | undefined)
})

const formRef = ref()
const fetchingOrder = ref(false)
const submitting = ref(false)
const checkingSlots = ref(false)
const savedRental = ref<Rental | null>(null)

// 日期选择器状态
const showStartDatePicker = ref(false)
const showEndDatePicker = ref(false)
const startDateParts = ref(dayjs().format('YYYY-MM-DD').split('-'))
const endDateParts = ref(dayjs().add(3, 'day').format('YYYY-MM-DD').split('-'))

// 各种 Picker 状态
const showModelPicker = ref(false)
const showDevicePicker = ref(false)
const showPhoneHolderPicker = ref(false)
const showTripodPicker = ref(false)

// 可选项数据
const deviceModels = ref<DeviceModel[]>([])
const availableSlots = ref<any[]>([])
const accessories = ref<{ phoneHolders: Device[], tripods: Device[] }>({ phoneHolders: [], tripods: [] })

// 选中名称（显示用）
const selectedModelName = ref('')
const selectedDeviceName = ref('')
const selectedPhoneHolderName = ref('')
const selectedTripodName = ref('')

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
  availableSlots.value.map((s: any) => ({
    text: s.device?.name || `设备${s.device?.id}`,
    value: s.device?.id
  }))
)
const phoneHolderColumns = computed(() => [
  { text: '无', value: null },
  ...accessories.value.phoneHolders.map(d => ({ text: d.name, value: d.id }))
])
const tripodColumns = computed(() => [
  { text: '无', value: null },
  ...accessories.value.tripods.map(d => ({ text: d.name, value: d.id }))
])

// 自动计算发货/入库时间
const shipOutDisplay = computed(() => {
  if (!form.value.startDate) return '—'
  return dayjs(form.value.startDate)
    .subtract(form.value.logisticsDays + 1, 'day')
    .format('YYYY-MM-DD')
})

const shipInDisplay = computed(() => {
  if (!form.value.endDate) return '—'
  return dayjs(form.value.endDate)
    .add(form.value.logisticsDays + 1, 'day')
    .format('YYYY-MM-DD')
})

// 监听 destination → 自动提取手机号
watch(() => form.value.destination, (val) => {
  if (val && !form.value.customerPhone) {
    const phone = extractPhoneNumber(val)
    if (phone) form.value.customerPhone = phone
  }
})

// 日期/型号变化时重新查找可用设备
const checkAvailability = async () => {
  if (!form.value.startDate || !form.value.endDate || !form.value.modelId) return
  checkingSlots.value = true
  form.value.deviceId = null
  selectedDeviceName.value = ''
  availableSlots.value = []
  try {
    const result = await ganttStore.findAvailableSlot(
      form.value.startDate,
      form.value.endDate,
      form.value.logisticsDays,
      form.value.modelId,
      false
    )
    if (result.availableDevices && result.availableDevices.length > 0) {
      availableSlots.value = result.availableDevices.map((d: any) => ({ device: d }))
    } else if (result.device) {
      availableSlots.value = [result]
    }
    if (!availableSlots.value.length) {
      showToast({ message: '无可用设备', type: 'fail' })
    }
  } catch (e: any) {
    showToast({ message: e.message || '查找档期失败', type: 'fail' })
  } finally {
    checkingSlots.value = false
  }
}

watch([() => form.value.startDate, () => form.value.endDate, () => form.value.modelId, () => form.value.logisticsDays], () => {
  checkAvailability()
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
  showDevicePicker.value = false
}

const onPhoneHolderConfirm = ({ selectedValues, selectedOptions }: any) => {
  form.value.phoneHolderId = selectedValues[0]
  selectedPhoneHolderName.value = selectedOptions[0]?.text ?? '无'
  showPhoneHolderPicker.value = false
}

const onTripodConfirm = ({ selectedValues, selectedOptions }: any) => {
  form.value.tripodId = selectedValues[0]
  selectedTripodName.value = selectedOptions[0]?.text ?? '无'
  showTripodPicker.value = false
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
      const fullAddress = [d.receiver_name, d.receiver_mobile, d.prov_name, d.city_name, d.area_name, d.town_name, d.address].filter(Boolean).join(' ')
      form.value.destination = fullAddress || form.value.destination
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

    const accessoriesArr: any[] = []
    if (form.value.phoneHolderId) {
      accessoriesArr.push({ id: form.value.phoneHolderId, is_bundled: false })
    }
    if (form.value.tripodId) {
      accessoriesArr.push({ id: form.value.tripodId, is_bundled: false })
    }

    const rentalData = {
      device_id: form.value.deviceId,
      start_date: form.value.startDate,
      end_date: form.value.endDate,
      customer_name: form.value.customerName,
      customer_phone: form.value.customerPhone,
      destination: form.value.destination,
      order_amount: form.value.orderAmount ? parseFloat(form.value.orderAmount) : undefined,
      buyer_id: form.value.buyerId || undefined,
      xianyu_order_no: form.value.xianyuOrderNo || undefined,
      logistics_days: form.value.logisticsDays,
      ship_out_time: shipTimes.ship_out_time,
      ship_in_time: shipTimes.ship_in_time,
      includes_handle: form.value.bundledAccessories.includes('handle'),
      includes_lens_mount: form.value.bundledAccessories.includes('lens_mount'),
      photo_transfer: form.value.photoTransfer,
      lens_combo: form.value.lensCombo,
      accessories: accessoriesArr
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
    onClose: () => router.back(),
  })
}

const handleConfirmationClosed = () => {
  savedRental.value = null
  router.back()
}

// 加载设备型号列表和配件列表
const loadInitData = async () => {
  try {
    const [modelsRes, accessoriesRes] = await Promise.all([
      axios.get('/api/device-models'),
      axios.get('/api/devices?is_accessory=true')
    ])
    if (modelsRes.data.success) {
      deviceModels.value = modelsRes.data.data || []
    }
    const all: Device[] = accessoriesRes.data.devices || []
    accessories.value.phoneHolders = all.filter(d =>
      d.model?.toLowerCase().includes('phone_holder') ||
      d.model?.includes('手机支架') ||
      d.name?.includes('手机支架')
    )
    accessories.value.tripods = all.filter(d =>
      d.model?.toLowerCase().includes('tripod') ||
      d.model?.includes('三脚架') ||
      d.name?.includes('三脚架')
    )
  } catch (e) {
    console.error('加载初始数据失败:', e)
  }
}

onMounted(async () => {
  // 先确保甘特store有设备数据
  if (!ganttStore.devices.length) {
    await ganttStore.loadData()
  }
  await loadInitData()
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
