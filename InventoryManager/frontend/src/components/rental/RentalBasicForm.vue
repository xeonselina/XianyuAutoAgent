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

    <!-- 客户联系信息 -->
    <el-form-item label="客户电话" prop="customerPhone">
      <el-input
        v-model="form.customerPhone"
        placeholder="请输入手机号码"
        maxlength="11"
      />
    </el-form-item>

    <el-form-item label="收件信息" prop="destination">
      <el-input
        v-model="form.destination"
        type="textarea"
        :rows="3"
        placeholder="请填写详细的收件地址、收件人姓名等信息"
      />
    </el-form-item>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import VueDatePicker from '@vuepic/vue-datepicker'
import type { Device, Rental } from '@/stores/gantt'

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

const handleDeviceChange = (deviceId: number) => {
  emit('device-change', deviceId)
}

const handleEndDateChange = (date: Date) => {
  emit('end-date-change', date)
}

const handleDeviceSelectorFocus = () => {
  emit('device-selector-focus')
}
</script>

<style scoped>
.form-tip {
  font-size: 12px;
  color: var(--el-text-color-placeholder);
  margin-top: 4px;
}
</style>