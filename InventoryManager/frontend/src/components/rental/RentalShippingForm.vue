<template>
  <div class="rental-shipping-form">
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

    <!-- 运单号管理 -->
    <el-form-item label="寄出运单号" prop="shipOutTrackingNo">
      <div class="tracking-input-group">
        <el-input
          v-model="form.shipOutTrackingNo"
          placeholder="如有请填写"
          style="flex: 1;"
        />
        <el-button
          type="primary"
          size="small"
          :loading="queryingShipOut"
          :disabled="!form.shipOutTrackingNo || !form.shipOutTrackingNo.trim()"
          @click="queryShipOutTracking"
          style="margin-left: 8px;"
        >
          <el-icon><Search /></el-icon>
          查询
        </el-button>
      </div>
    </el-form-item>

    <el-form-item label="寄回运单号" prop="shipInTrackingNo">
      <div class="tracking-input-group">
        <el-input
          v-model="form.shipInTrackingNo"
          placeholder="如有请填写"
          style="flex: 1;"
        />
        <el-button
          type="primary"
          size="small"
          :loading="queryingShipIn"
          :disabled="!form.shipInTrackingNo || !form.shipInTrackingNo.trim()"
          @click="queryShipInTracking"
          style="margin-left: 8px;"
        >
          <el-icon><Search /></el-icon>
          查询
        </el-button>
      </div>
    </el-form-item>

    <!-- 时间管理 -->
    <el-form-item label="寄出时间" prop="shipOutTime">
      <VueDatePicker
        v-model="form.shipOutTime"
        placeholder="选择寄出时间"
        :format="'yyyy-MM-dd HH:mm'"
        :locale="'zh-cn'"
        :week-start="1"
        :enable-time-picker="true"
        time-picker-inline
        auto-apply
        :seconds="false"
        style="width: 100%"
        @update:model-value="handleShipOutTimeChange"
      />
      <div class="form-tip">设备寄出的具体时间</div>
    </el-form-item>

    <el-form-item label="收回时间" prop="shipInTime">
      <VueDatePicker
        v-model="form.shipInTime"
        placeholder="选择收回时间"
        :format="'yyyy-MM-dd HH:mm'"
        :locale="'zh-cn'"
        :week-start="1"
        :enable-time-picker="true"
        time-picker-inline
        auto-apply
        :seconds="false"
        style="width: 100%"
        @update:model-value="handleShipInTimeChange"
      />
      <div class="form-tip">设备收回时间的具体时间</div>
    </el-form-item>

    <!-- 状态管理 -->
    <el-form-item label="租赁状态" prop="status">
      <el-select
        v-model="form.status"
        placeholder="选择租赁状态"
        style="width: 100%"
        @change="handleStatusChange"
      >
        <el-option label="未发货" value="not_shipped" />
        <el-option label="已发货" value="shipped" />
        <el-option label="已收回" value="returned" />
        <el-option label="已完成" value="completed" />
        <el-option label="已取消" value="cancelled" />
      </el-select>
      <div class="form-tip">修改状态会同步更新附件状态</div>
    </el-form-item>
  </div>
</template>

<script setup lang="ts">
import { watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Search } from '@element-plus/icons-vue'
import VueDatePicker from '@vuepic/vue-datepicker'
import { extractPhoneNumber } from '@/utils/phoneExtractor'

interface Props {
  form: any
  queryingShipOut: boolean
  queryingShipIn: boolean
}

const props = defineProps<Props>()

const emit = defineEmits<{
  'query-ship-out': []
  'query-ship-in': []
  'ship-out-time-change': [time: Date]
  'ship-in-time-change': [time: Date]
  'status-change': [status: string]
}>()

const queryShipOutTracking = () => {
  emit('query-ship-out')
}

const queryShipInTracking = () => {
  emit('query-ship-in')
}

const handleShipOutTimeChange = (time: Date) => {
  emit('ship-out-time-change', time)
}

const handleShipInTimeChange = (time: Date) => {
  emit('ship-in-time-change', time)
}

const handleStatusChange = (status: string) => {
  emit('status-change', status)
}

// Watch destination change to extract phone number
watch(() => props.form.destination, (newDestination) => {
  // 只有当客户电话为空时才自动提取
  if (newDestination && !props.form.customerPhone) {
    const extractedPhone = extractPhoneNumber(newDestination)
    if (extractedPhone) {
      props.form.customerPhone = extractedPhone
      ElMessage.success('已自动从收件信息中提取手机号')
    }
  }
})
</script>

<style scoped>
.tracking-input-group {
  display: flex;
  align-items: center;
  width: 100%;
}

.form-tip {
  font-size: 12px;
  color: var(--el-text-color-placeholder);
  margin-top: 4px;
}
</style>