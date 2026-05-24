<template>
  <div class="form-view">
    <van-nav-bar
      title="编辑租赁"
      left-arrow
      @click-left="$router.back()"
      :border="false"
    />

    <div class="form-scroll" v-if="!initialLoading">
      <van-form ref="formRef" @submit="onSubmit">
        <!-- 订单信息 -->
        <van-cell-group inset title="订单信息">
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
            v-model="form.xianyuOrderNo"
            label="闲鱼订单号"
            placeholder="选填"
            clearable
          />
          <van-field
            v-model="form.orderAmount"
            label="订单金额"
            placeholder="选填"
            type="number"
          />
        </van-cell-group>

        <!-- 租赁信息 -->
        <van-cell-group inset title="租赁信息" style="margin-top:12px">
          <!-- 设备型号（只读显示） -->
          <van-cell title="起租日" :value="form.startDate" />

          <!-- 还租日（可编辑） -->
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

          <!-- 设备（可换） -->
          <van-field
            v-model="selectedDeviceName"
            readonly
            clickable
            label="设备"
            placeholder="请选择"
            required
            :rules="[{ required: true, message: '请选择设备' }]"
            @click="showDevicePicker = true"
          >
            <template #right-icon>
              <van-loading v-if="checkingConflict" size="16" />
              <van-icon v-else-if="conflictWarning" name="warning-o" color="#ff976a" />
            </template>
          </van-field>

          <!-- 物流天数 -->
          <van-field label="物流天数">
            <template #input>
              <van-stepper v-model="form.logisticsDays" :min="0" :max="7" />
            </template>
          </van-field>
        </van-cell-group>

        <!-- 物流信息 -->
        <van-cell-group inset title="物流信息" style="margin-top:12px">
          <!-- 发货运单号 -->
          <van-field
            v-model="form.shipOutTrackingNo"
            label="发货单号"
            placeholder="选填"
            clearable
          >
            <template #button>
              <van-button
                size="small"
                type="primary"
                :loading="queryingShipOut"
                @click="queryTrackingStatus('out')"
              >查询</van-button>
            </template>
          </van-field>

          <!-- 入库运单号 -->
          <van-field
            v-model="form.shipInTrackingNo"
            label="入库单号"
            placeholder="选填"
            clearable
          >
            <template #button>
              <van-button
                size="small"
                type="primary"
                :loading="queryingShipIn"
                @click="queryTrackingStatus('in')"
              >查询</van-button>
            </template>
          </van-field>

          <!-- 发货时间 -->
          <van-field
            v-model="shipOutTimeDisplay"
            readonly
            clickable
            label="发货时间"
            placeholder="请选择"
            @click="showShipOutDatePicker = true"
          />

          <!-- 入库时间 -->
          <van-field
            v-model="shipInTimeDisplay"
            readonly
            clickable
            label="入库时间"
            placeholder="请选择"
            @click="showShipInDatePicker = true"
          />
        </van-cell-group>

        <!-- 订单状态 -->
        <van-cell-group inset title="订单状态" style="margin-top:12px">
          <van-field
            v-model="selectedStatusLabel"
            readonly
            clickable
            label="状态"
            placeholder="请选择"
            @click="showStatusPicker = true"
          />
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
          >保存修改</van-button>
          <van-button
            v-if="form.status === 'not_shipped'"
            type="warning"
            block
            :loading="shippingToXianyu"
            style="margin-top: 8px"
            @click="onShipToXianyu"
          >发货到闲鱼</van-button>
        </div>
      </van-form>
    </div>

    <div class="loading-center" v-else>
      <van-loading color="#409eff" />
    </div>

    <!-- 设备选择器 -->
    <van-popup v-model:show="showDevicePicker" position="bottom" round>
      <van-picker
        :columns="deviceColumns"
        @confirm="onDeviceConfirm"
        @cancel="showDevicePicker = false"
        show-toolbar
        title="选择设备"
      />
    </van-popup>

    <!-- 状态选择器 -->
    <van-popup v-model:show="showStatusPicker" position="bottom" round>
      <van-picker
        :columns="statusColumns"
        @confirm="onStatusConfirm"
        @cancel="showStatusPicker = false"
        show-toolbar
        title="选择状态"
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

    <!-- 发货时间日期选择器 -->
    <van-popup v-model:show="showShipOutDatePicker" position="bottom" round>
      <div class="datetime-picker-wrap">
        <div class="datetime-picker-title">选择发货时间</div>
        <van-date-picker
          v-model="shipOutDateParts"
          title=""
          :show-toolbar="false"
          @update:model-value="v => shipOutDateParts = v"
        />
        <div class="time-row">
          <span class="time-label">时间</span>
          <van-field
            v-model="shipOutTimeStr"
            type="time"
            placeholder="09:00"
            class="time-input"
          />
        </div>
        <div class="picker-actions">
          <van-button plain @click="showShipOutDatePicker = false">取消</van-button>
          <van-button type="primary" @click="onShipOutTimeConfirm">确认</van-button>
        </div>
      </div>
    </van-popup>

    <!-- 入库时间日期选择器 -->
    <van-popup v-model:show="showShipInDatePicker" position="bottom" round>
      <div class="datetime-picker-wrap">
        <div class="datetime-picker-title">选择入库时间</div>
        <van-date-picker
          v-model="shipInDateParts"
          title=""
          :show-toolbar="false"
          @update:model-value="v => shipInDateParts = v"
        />
        <div class="time-row">
          <span class="time-label">时间</span>
          <van-field
            v-model="shipInTimeStr"
            type="time"
            placeholder="18:00"
            class="time-input"
          />
        </div>
        <div class="picker-actions">
          <van-button plain @click="showShipInDatePicker = false">取消</van-button>
          <van-button type="primary" @click="onShipInTimeConfirm">确认</van-button>
        </div>
      </div>
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
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { showToast } from 'vant'
import axios from 'axios'
import dayjs from 'dayjs'
import { useGanttStore } from '@/stores/gantt'
import type { Rental, Device } from '@/stores/gantt'
import { useConflictDetection } from '@/composables/useConflictDetection'

const router = useRouter()
const route = useRoute()
const ganttStore = useGanttStore()
const conflictDetection = useConflictDetection()

const rentalId = computed(() => Number(route.params.id))

// 加载状态
const initialLoading = ref(true)
const submitting = ref(false)
const shippingToXianyu = ref(false)
const checkingConflict = ref(false)
const conflictWarning = ref(false)
const queryingShipOut = ref(false)
const queryingShipIn = ref(false)

// Picker 显示状态
const showDevicePicker = ref(false)
const showStatusPicker = ref(false)
const showEndDatePicker = ref(false)
const showShipOutDatePicker = ref(false)
const showShipInDatePicker = ref(false)
const showPhoneHolderPicker = ref(false)
const showTripodPicker = ref(false)

// 表单数据
const form = ref({
  customerName: '',
  customerPhone: '',
  destination: '',
  xianyuOrderNo: '',
  orderAmount: '',
  startDate: '',
  endDate: '',
  deviceId: null as number | null,
  logisticsDays: 1,
  shipOutTrackingNo: '',
  shipInTrackingNo: '',
  shipOutTime: '',   // ISO string
  shipInTime: '',    // ISO string
  status: 'not_shipped',
  bundledAccessories: [] as string[],
  photoTransfer: false,
  phoneHolderId: null as number | null,
  tripodId: null as number | null
})

const formRef = ref()

// 选中名称（显示用）
const selectedDeviceName = ref('')
const selectedStatusLabel = ref('')
const selectedPhoneHolderName = ref('')
const selectedTripodName = ref('')

// 配件数据
const accessories = ref<{ phoneHolders: Device[], tripods: Device[] }>({ phoneHolders: [], tripods: [] })

// 日期 picker 的数组状态
const endDateParts = ref<string[]>([])
const shipOutDateParts = ref<string[]>([])
const shipOutTimeStr = ref('09:00')
const shipInDateParts = ref<string[]>([])
const shipInTimeStr = ref('18:00')

// 所有可用设备
const allDevices = ref<Device[]>([])

const endDateMin = computed(() => {
  return form.value.startDate ? new Date(form.value.startDate) : undefined
})

// 发货时间显示
const shipOutTimeDisplay = computed(() => {
  if (!form.value.shipOutTime) return '—'
  return dayjs(form.value.shipOutTime).format('YYYY-MM-DD HH:mm')
})

// 入库时间显示
const shipInTimeDisplay = computed(() => {
  if (!form.value.shipInTime) return '—'
  return dayjs(form.value.shipInTime).format('YYYY-MM-DD HH:mm')
})

// Picker 列数据
const deviceColumns = computed(() =>
  allDevices.value
    .filter(d => !d.is_accessory && d.status === 'online')
    .map(d => ({ text: d.name, value: d.id }))
)

const phoneHolderColumns = computed(() => [
  { text: '无', value: null },
  ...accessories.value.phoneHolders.map(d => ({ text: d.name, value: d.id }))
])
const tripodColumns = computed(() => [
  { text: '无', value: null },
  ...accessories.value.tripods.map(d => ({ text: d.name, value: d.id }))
])

const STATUS_OPTS = [
  { text: '待发货',  value: 'not_shipped' },
  { text: '已预约',  value: 'scheduled_for_shipping' },
  { text: '已发货',  value: 'shipped' },
  { text: '已还租',  value: 'returned' },
  { text: '已完成',  value: 'completed' },
  { text: '已取消',  value: 'cancelled' }
]
const statusColumns = STATUS_OPTS

// 初始化表单
const initForm = (rental: Rental) => {
  form.value.customerName = rental.customer_name || ''
  form.value.customerPhone = rental.customer_phone || ''
  form.value.destination = rental.destination || ''
  form.value.xianyuOrderNo = (rental as any).xianyu_order_no || ''
  form.value.orderAmount = (rental as any).order_amount ? String((rental as any).order_amount) : ''
  form.value.startDate = rental.start_date || ''
  form.value.endDate = rental.end_date || ''
  form.value.deviceId = rental.device_id
  form.value.logisticsDays = (rental as any).logistics_days ?? 1
  form.value.shipOutTrackingNo = rental.ship_out_tracking_no || ''
  form.value.shipInTrackingNo = rental.ship_in_tracking_no || ''
  form.value.shipOutTime = rental.ship_out_time || ''
  form.value.shipInTime = rental.ship_in_time || ''
  form.value.status = rental.status || 'not_shipped'
  form.value.bundledAccessories = []
  if (rental.includes_handle) form.value.bundledAccessories.push('handle')
  if (rental.includes_lens_mount) form.value.bundledAccessories.push('lens_mount')
  form.value.photoTransfer = rental.photo_transfer || false

  // 配件（手机支架、三脚架）
  form.value.phoneHolderId = null
  form.value.tripodId = null
  selectedPhoneHolderName.value = ''
  selectedTripodName.value = ''
  const rentedAccessories = (rental as any).accessories || []
  for (const acc of rentedAccessories) {
    if (acc.model?.toLowerCase().includes('phone_holder') || acc.name?.includes('手机支架')) {
      form.value.phoneHolderId = acc.id
      selectedPhoneHolderName.value = acc.name || '手机支架'
    } else if (acc.model?.toLowerCase().includes('tripod') || acc.name?.includes('三脚架')) {
      form.value.tripodId = acc.id
      selectedTripodName.value = acc.name || '三脚架'
    }
  }

  // 设备名称
  selectedDeviceName.value = rental.device?.name || `设备${rental.device_id}`

  // 状态标签
  const statusOpt = STATUS_OPTS.find(o => o.value === rental.status)
  selectedStatusLabel.value = statusOpt?.text || rental.status

  // 日期 parts
  if (rental.end_date) {
    endDateParts.value = rental.end_date.split('-')
  }

  // 发货时间 parts
  if (rental.ship_out_time) {
    const d = dayjs(rental.ship_out_time)
    shipOutDateParts.value = d.format('YYYY-MM-DD').split('-')
    shipOutTimeStr.value = d.format('HH:mm')
  }

  // 入库时间 parts
  if (rental.ship_in_time) {
    const d = dayjs(rental.ship_in_time)
    shipInDateParts.value = d.format('YYYY-MM-DD').split('-')
    shipInTimeStr.value = d.format('HH:mm')
  }
}

// Picker 确认处理
const onDeviceConfirm = ({ selectedValues, selectedOptions }: any) => {
  const newDeviceId = selectedValues[0]
  if (newDeviceId !== form.value.deviceId) {
    form.value.deviceId = newDeviceId
    selectedDeviceName.value = selectedOptions[0]?.text ?? ''
    checkDeviceConflict()
  }
  showDevicePicker.value = false
}

const onStatusConfirm = ({ selectedValues, selectedOptions }: any) => {
  form.value.status = selectedValues[0]
  selectedStatusLabel.value = selectedOptions[0]?.text ?? ''
  showStatusPicker.value = false
}

const onEndDateConfirm = ({ selectedValues }: any) => {
  form.value.endDate = selectedValues.join('-')
  endDateParts.value = selectedValues
  showEndDatePicker.value = false
}

const onPhoneHolderConfirm = ({ selectedValues, selectedOptions }: any) => {
  form.value.phoneHolderId = selectedValues[0] ?? null
  selectedPhoneHolderName.value = selectedValues[0] ? (selectedOptions[0]?.text ?? '') : ''
  showPhoneHolderPicker.value = false
}

const onTripodConfirm = ({ selectedValues, selectedOptions }: any) => {
  form.value.tripodId = selectedValues[0] ?? null
  selectedTripodName.value = selectedValues[0] ? (selectedOptions[0]?.text ?? '') : ''
  showTripodPicker.value = false
}

const onShipOutTimeConfirm = () => {
  if (shipOutDateParts.value.length === 3) {
    const dateStr = shipOutDateParts.value.join('-')
    const timeStr = shipOutTimeStr.value || '09:00'
    form.value.shipOutTime = dayjs(`${dateStr} ${timeStr}`).toISOString()
  }
  showShipOutDatePicker.value = false
}

const onShipInTimeConfirm = () => {
  if (shipInDateParts.value.length === 3) {
    const dateStr = shipInDateParts.value.join('-')
    const timeStr = shipInTimeStr.value || '18:00'
    form.value.shipInTime = dayjs(`${dateStr} ${timeStr}`).toISOString()
  }
  showShipInDatePicker.value = false
}

// 设备冲突检测
const checkDeviceConflict = async () => {
  if (!form.value.deviceId || !form.value.startDate || !form.value.endDate) return
  checkingConflict.value = true
  conflictWarning.value = false
  try {
    const hasConflict = await conflictDetection.checkDeviceConflict({
      deviceId: form.value.deviceId,
      startDate: form.value.startDate,
      endDate: form.value.endDate,
      logisticsDays: form.value.logisticsDays,
      excludeRentalId: rentalId.value
    })
    conflictWarning.value = hasConflict
    if (hasConflict) {
      showToast({ message: '所选设备在该时段有冲突', type: 'fail' })
    }
  } catch {
    // 忽略检测错误
  } finally {
    checkingConflict.value = false
  }
}

// 查询运单状态
const queryTrackingStatus = async (type: 'out' | 'in') => {
  const trackingNo = type === 'out' ? form.value.shipOutTrackingNo : form.value.shipInTrackingNo
  if (!trackingNo.trim()) {
    showToast('请先填写运单号')
    return
  }
  if (type === 'out') queryingShipOut.value = true
  else queryingShipIn.value = true
  try {
    const res = await axios.get(`/api/shipping/track/${trackingNo}`)
    if (res.data.success) {
      showToast({ message: `状态：${res.data.data?.status || '查询成功'}`, type: 'success' })
    } else {
      showToast({ message: res.data.error || '查询失败', type: 'fail' })
    }
  } catch (e: any) {
    showToast({ message: e.message || '查询失败', type: 'fail' })
  } finally {
    if (type === 'out') queryingShipOut.value = false
    else queryingShipIn.value = false
  }
}

// 提交
const onSubmit = async () => {
  if (!form.value.deviceId) {
    showToast('请选择设备')
    return
  }

  submitting.value = true
  try {
    const updateData: any = {
      customer_name: form.value.customerName,
      customer_phone: form.value.customerPhone,
      destination: form.value.destination,
      xianyu_order_no: form.value.xianyuOrderNo || undefined,
      order_amount: form.value.orderAmount ? parseFloat(form.value.orderAmount) : undefined,
      end_date: form.value.endDate,
      device_id: form.value.deviceId,
      logistics_days: form.value.logisticsDays,
      ship_out_tracking_no: form.value.shipOutTrackingNo || undefined,
      ship_in_tracking_no: form.value.shipInTrackingNo || undefined,
      ship_out_time: form.value.shipOutTime || undefined,
      ship_in_time: form.value.shipInTime || undefined,
      status: form.value.status,
      includes_handle: form.value.bundledAccessories.includes('handle'),
      includes_lens_mount: form.value.bundledAccessories.includes('lens_mount'),
      photo_transfer: form.value.photoTransfer,
      accessories: [
        ...(form.value.phoneHolderId ? [{ id: form.value.phoneHolderId, is_bundled: false }] : []),
        ...(form.value.tripodId ? [{ id: form.value.tripodId, is_bundled: false }] : [])
      ]
    }

    await ganttStore.updateRental(rentalId.value, updateData)
    showToast({ message: '修改保存成功', type: 'success' })
    router.back()
  } catch (e: any) {
    const errMsg = e.response?.data?.error || e.message || '保存失败'
    showToast({ message: errMsg, type: 'fail' })
  } finally {
    submitting.value = false
  }
}

const onShipToXianyu = async () => {
  shippingToXianyu.value = true
  try {
    await ganttStore.shipRentalToXianyu(rentalId.value)
    showToast({ message: '发货成功', type: 'success' })
    router.back()
  } catch (e: any) {
    showToast({ message: e.message || '发货失败', type: 'fail' })
  } finally {
    shippingToXianyu.value = false
  }
}

const loadAccessories = async () => {
  try {
    const res = await axios.get('/api/devices', { params: { is_accessory: true, per_page: 100 } })
    if (res.data.success) {
      const all: Device[] = res.data.data?.devices || []
      accessories.value.phoneHolders = all.filter(d =>
        d.model?.toLowerCase().includes('phone_holder') ||
        d.name?.includes('手机支架')
      )
      accessories.value.tripods = all.filter(d =>
        d.model?.toLowerCase().includes('tripod') ||
        d.name?.includes('三脚架')
      )
    }
  } catch (e) {
    console.error('加载配件数据失败:', e)
  }
}

onMounted(async () => {
  try {
    // 加载设备列表
    if (!ganttStore.devices.length) {
      await ganttStore.loadData()
    }
    allDevices.value = ganttStore.devices
    await loadAccessories()

    // 加载租赁数据
    const rental = await ganttStore.getRentalById(rentalId.value)
    if (!rental) {
      showToast({ message: '租赁记录不存在', type: 'fail' })
      router.back()
      return
    }
    initForm(rental)
  } catch (e) {
    showToast({ message: '加载数据失败', type: 'fail' })
    router.back()
  } finally {
    initialLoading.value = false
  }
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

.loading-center {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}

.submit-wrap {
  padding: 16px;
}

.datetime-picker-wrap {
  padding: 16px;
  padding-bottom: 24px;
}

.datetime-picker-title {
  font-size: 15px;
  font-weight: 600;
  color: #333;
  text-align: center;
  margin-bottom: 12px;
}

.time-row {
  display: flex;
  align-items: center;
  padding: 8px 0;
  border-top: 1px solid #eee;
  margin-top: 8px;
}

.time-label {
  font-size: 14px;
  color: #666;
  width: 52px;
  flex-shrink: 0;
}

.time-input {
  flex: 1;
}

.picker-actions {
  display: flex;
  gap: 12px;
  margin-top: 16px;
}

.picker-actions .van-button {
  flex: 1;
}
</style>
