<template>
  <div class="rental-basic-form">
    <!-- 设备选择 -->
    <el-form-item label="设备名称" prop="deviceId">
      <el-select
        v-model="form.deviceId"
        placeholder="选择设备"
        style="width: 100%"
        @change="handleDeviceChange"
        @focus="handleDeviceSelectorFocus"
        :loading="loadingDevices"
      >
        <el-option
          v-for="device in availableDevices"
          :key="device.id"
          :label="`${device.name} (${device.serial_number || '无序列号'})`"
          :value="device.id"
        >
          <div style="display: flex; justify-content: space-between; align-items: center;">
            <span>{{ device.name }}</span>
            <div style="font-size: 12px; color: #999; display: flex; align-items: center; gap: 8px;">
              <span v-if="device.serial_number">{{ device.serial_number }}</span>
              <el-tag v-if="device.conflicted" type="danger" size="small" effect="dark">
                时间冲突
              </el-tag>
            </div>
          </div>
        </el-option>
      </el-select>
      <div class="form-tip">选择不同设备会检查时间冲突</div>
    </el-form-item>

    <!-- 客户信息（只读） -->
    <el-form-item label="闲鱼 ID">
      <el-input :value="rental.customer_name" disabled />
    </el-form-item>

    <!-- 日期信息 -->
    <el-form-item label="开始日期">
      <el-input :value="rental.start_date" disabled />
      <div class="form-tip">开始日期不可修改</div>
    </el-form-item>

    <el-form-item label="结束日期" prop="endDate">
      <VueDatePicker
        v-model="form.endDate"
        placeholder="选择结束日期"
        format="yyyy-MM-dd"
        preview-format="yyyy-MM-dd"
        :locale="'zh-cn'"
        :week-start="1"
        :enable-time-picker="false"
        :min-date="minSelectableDate || undefined"
        auto-apply
        style="width: 100%"
        @update:model-value="handleEndDateChange"
      />
      <div class="form-tip">修改后将自动更新收回时间</div>
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
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import VueDatePicker from '@vuepic/vue-datepicker'
import type { Device, Rental } from '@/stores/gantt'
import axios from 'axios'

interface DeviceWithConflictStatus extends Device {
  conflicted?: boolean
}

interface Props {
  form: any
  rental: Rental
  availableDevices: DeviceWithConflictStatus[]
  loadingDevices: boolean
  minSelectableDate: Date | null
}

const props = defineProps<Props>()

const emit = defineEmits<{
  'device-change': [deviceId: number]
  'end-date-change': [date: Date]
  'device-selector-focus': []
}>()

// 闲鱼订单信息拉取状态
const fetchingOrder = ref(false)

const handleDeviceChange = (deviceId: number) => {
  emit('device-change', deviceId)
}

const handleEndDateChange = (date: Date) => {
  emit('end-date-change', date)
}

const handleDeviceSelectorFocus = () => {
  emit('device-selector-focus')
}

// 拉取闲鱼订单信息
const handleFetchOrderInfo = async () => {
  const orderNo = props.form.xianyuOrderNo?.trim()

  if (!orderNo) {
    ElMessage.warning('请先输入订单号')
    return
  }

  fetchingOrder.value = true

  try {
    console.log('开始请求订单信息，订单号:', orderNo)

    const response = await axios.post('/api/rentals/fetch-xianyu-order', {
      order_no: orderNo
    })

    console.log('API响应:', response.data)
    console.log('响应成功:', response.data.success)
    console.log('响应数据:', response.data.data)

    if (response.data.success && response.data.data) {
      const orderData = response.data.data

      console.log('=== 开始填充订单数据 ===')
      console.log('订单数据:', orderData)

      // 组合收件信息：姓名 + 电话 + 地址
      const destinationParts = []

      // 添加收件人姓名
      if (orderData.receiver_name) {
        destinationParts.push(orderData.receiver_name)
      }

      // 添加收件人电话
      if (orderData.receiver_mobile) {
        destinationParts.push(orderData.receiver_mobile)
      }

      // 添加完整地址
      const addressParts = [
        orderData.prov_name,
        orderData.city_name,
        orderData.area_name,
        orderData.town_name,
        orderData.address
      ].filter(Boolean)

      if (addressParts.length > 0) {
        destinationParts.push(addressParts.join(''))
      }

      if (destinationParts.length > 0) {
        props.form.destination = destinationParts.join(' ')
        console.log('填充收件信息:', props.form.destination)
      }

      // 自动填充买家ID
      if (orderData.buyer_eid) {
        props.form.buyerId = orderData.buyer_eid
        console.log('填充买家ID:', orderData.buyer_eid)
      }

      // 自动填充订单金额（从分转换为元）
      if (orderData.pay_amount) {
        props.form.orderAmount = (orderData.pay_amount / 100).toFixed(2)
        console.log('填充订单金额:', props.form.orderAmount)
      }

      // 最后填充手机号（覆盖可能被watch自动提取的手机号）
      if (orderData.receiver_mobile) {
        props.form.customerPhone = orderData.receiver_mobile
        console.log('填充手机号:', orderData.receiver_mobile)
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
</script>

<style scoped>
.form-tip {
  font-size: 12px;
  color: var(--el-text-color-placeholder);
  margin-top: 4px;
}
</style>