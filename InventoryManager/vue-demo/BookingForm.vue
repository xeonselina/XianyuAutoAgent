<template>
  <el-form :model="form" :rules="rules" ref="formRef" label-width="120px">
    <el-form-item label="开始日期" prop="startDate">
      <el-date-picker
        v-model="form.startDate"
        type="date"
        placeholder="选择开始日期"
        :disabled-date="disabledDate"
        style="width: 100%"
      />
    </el-form-item>

    <el-form-item label="结束日期" prop="endDate">
      <el-date-picker
        v-model="form.endDate"
        type="date"
        placeholder="选择结束日期"
        :disabled-date="disabledDate"
        style="width: 100%"
      />
    </el-form-item>

    <el-form-item label="物流天数" prop="logisticsDays">
      <el-input-number
        v-model="form.logisticsDays"
        :min="1"
        :max="7"
        style="width: 100%"
      />
    </el-form-item>

    <el-form-item label="客户姓名" prop="customerName">
      <el-input v-model="form.customerName" placeholder="请输入客户姓名" />
    </el-form-item>

    <el-form-item label="客户电话" prop="customerPhone">
      <el-input v-model="form.customerPhone" placeholder="请输入手机号码" />
    </el-form-item>

    <el-form-item label="收件信息" prop="destination">
      <el-input
        v-model="form.destination"
        type="textarea"
        :rows="3"
        placeholder="请填写详细的收件地址、收件人姓名等信息"
      />
    </el-form-item>

    <!-- 可用档期显示 -->
    <el-alert
      v-if="availableSlot"
      :title="`找到可用设备：${availableSlot.device.name}`"
      type="success"
      show-icon
      :closable="false"
      class="mb-3"
    >
      <template #default>
        <p>寄出时间：{{ formatDateTime(availableSlot.shipOutDate) }}</p>
        <p>收回时间：{{ formatDateTime(availableSlot.shipInDate) }}</p>
      </template>
    </el-alert>

    <el-form-item>
      <el-button @click="findAvailableSlot" :loading="searching">
        查找档期
      </el-button>
      <el-button
        type="primary"
        @click="submitBooking"
        :disabled="!availableSlot"
        :loading="submitting"
      >
        提交预定
      </el-button>
      <el-button @click="$emit('cancel')">取消</el-button>
    </el-form-item>
  </el-form>
</template>

<script setup>
import { ref, reactive, computed } from 'vue'
import { ElMessage } from 'element-plus'
import axios from 'axios'

// 发射事件
const emit = defineEmits(['submit', 'cancel'])

// 响应式状态
const formRef = ref()
const searching = ref(false)
const submitting = ref(false)
const availableSlot = ref(null)

// 表单数据
const form = reactive({
  startDate: '',
  endDate: '',
  logisticsDays: 1,
  customerName: '',
  customerPhone: '',
  destination: ''
})

// 表单验证规则
const rules = {
  startDate: [{ required: true, message: '请选择开始日期', trigger: 'change' }],
  endDate: [{ required: true, message: '请选择结束日期', trigger: 'change' }],
  customerName: [{ required: true, message: '请输入客户姓名', trigger: 'blur' }],
  customerPhone: [
    { required: true, message: '请输入客户电话', trigger: 'blur' },
    { pattern: /^1[3-9]\d{9}$/, message: '请输入正确的手机号码', trigger: 'blur' }
  ]
}

// 方法
const disabledDate = (date) => {
  return date < new Date().setHours(0, 0, 0, 0)
}

const findAvailableSlot = async () => {
  if (!form.startDate || !form.endDate) {
    ElMessage.warning('请先选择开始和结束日期')
    return
  }

  searching.value = true
  try {
    const response = await axios.post('/api/rentals/find-slot', {
      start_date: formatDate(form.startDate),
      end_date: formatDate(form.endDate),
      logistics_days: form.logisticsDays
    })

    if (response.data.success) {
      const data = response.data.data
      availableSlot.value = {
        device: data.device,
        shipOutDate: new Date(data.ship_out_date),
        shipInDate: new Date(data.ship_in_date)
      }
      ElMessage.success(response.data.message || '找到可用档期')
    } else {
      ElMessage.error(response.data.error)
      availableSlot.value = null
    }
  } catch (error) {
    ElMessage.error('查找档期失败')
    availableSlot.value = null
  } finally {
    searching.value = false
  }
}

const submitBooking = async () => {
  if (!availableSlot.value) {
    ElMessage.warning('请先查找可用档期')
    return
  }

  try {
    await formRef.value.validate()
  } catch {
    return
  }

  submitting.value = true
  try {
    const bookingData = {
      device_id: availableSlot.value.device.id,
      start_date: formatDate(form.startDate),
      end_date: formatDate(form.endDate),
      customer_name: form.customerName,
      customer_phone: form.customerPhone,
      destination: form.destination,
      ship_out_time: formatDate(availableSlot.value.shipOutDate),
      ship_in_time: formatDate(availableSlot.value.shipInDate)
    }

    emit('submit', bookingData)
  } finally {
    submitting.value = false
  }
}

const formatDate = (date) => {
  return date.toISOString().split('T')[0]
}

const formatDateTime = (date) => {
  return date.toLocaleString('zh-CN')
}
</script>

<style scoped>
.mb-3 {
  margin-bottom: 16px;
}
</style>
