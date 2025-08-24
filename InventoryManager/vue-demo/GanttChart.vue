<template>
  <div class="gantt-container">
    <!-- 工具栏 -->
    <div class="toolbar mb-3">
      <el-row :gutter="10" align="middle">
        <el-col :span="8">
          <el-button-group>
            <el-button @click="navigateWeek(-1)">上周</el-button>
            <el-button @click="goToToday">今天</el-button>
            <el-button @click="navigateWeek(1)">下周</el-button>
          </el-button-group>
        </el-col>
        <el-col :span="8">
          <span class="current-period">{{ currentPeriod }}</span>
        </el-col>
        <el-col :span="8" class="text-right">
          <el-button type="primary" @click="showBookingModal = true">
            预定设备
          </el-button>
          <el-button @click="refreshData">刷新</el-button>
        </el-col>
      </el-row>
    </div>

    <!-- 甘特图 -->
    <div class="gantt-chart" ref="ganttChart">
      <!-- Vue会自动渲染，无需手动DOM操作 -->
      <GanttHeader :dates="dateRange" />
      <GanttRow 
        v-for="device in devices" 
        :key="device.id"
        :device="device"
        :rentals="getRentalsForDevice(device.id)"
        :dates="dateRange"
        @edit-rental="handleEditRental"
      />
    </div>

    <!-- 预定设备对话框 -->
    <el-dialog v-model="showBookingModal" title="预定设备" width="600px">
      <BookingForm 
        @submit="handleBookingSubmit"
        @cancel="showBookingModal = false"
      />
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import axios from 'axios'

// 响应式状态
const devices = ref([])
const rentals = ref([])
const currentDate = ref(new Date())
const showBookingModal = ref(false)

// 计算属性
const dateRange = computed(() => {
  // 自动计算日期范围，无需手动DOM更新
  const start = new Date(currentDate.value)
  start.setDate(start.getDate() - 15)
  const end = new Date(currentDate.value)
  end.setDate(end.getDate() + 15)
  return { start, end }
})

const currentPeriod = computed(() => {
  // 自动格式化显示文本
  const { start, end } = dateRange.value
  return `${formatDate(start)} - ${formatDate(end)}`
})

// 方法
const loadData = async () => {
  try {
    const response = await axios.get('/api/gantt/data', {
      params: {
        start_date: formatDate(dateRange.value.start),
        end_date: formatDate(dateRange.value.end)
      }
    })
    
    if (response.data.success) {
      devices.value = response.data.data.devices
      rentals.value = response.data.data.rentals
    }
  } catch (error) {
    ElMessage.error('加载数据失败')
  }
}

const navigateWeek = (weeks) => {
  const newDate = new Date(currentDate.value)
  newDate.setDate(newDate.getDate() + (weeks * 7))
  currentDate.value = newDate
  loadData() // Vue会自动重新渲染
}

const goToToday = () => {
  currentDate.value = new Date()
  loadData()
}

const refreshData = () => {
  loadData()
}

const getRentalsForDevice = (deviceId) => {
  return rentals.value.filter(rental => rental.device_id === deviceId)
}

const handleBookingSubmit = async (bookingData) => {
  try {
    const response = await axios.post('/api/rentals', bookingData)
    if (response.data.success) {
      ElMessage.success('预定成功！')
      showBookingModal.value = false
      loadData()
    }
  } catch (error) {
    ElMessage.error('预定失败')
  }
}

const formatDate = (date) => {
  return date.toISOString().split('T')[0]
}

// 生命周期
onMounted(() => {
  loadData()
})
</script>

<style scoped>
.gantt-container {
  padding: 20px;
}

.current-period {
  font-weight: bold;
  font-size: 16px;
}

.gantt-chart {
  border: 1px solid #ddd;
  border-radius: 4px;
  overflow: auto;
  max-height: 70vh;
}

.text-right {
  text-align: right;
}
</style>
