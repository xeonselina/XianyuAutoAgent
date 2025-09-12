<template>
  <el-dialog
    v-model="dialogVisible"
    title="编辑租赁记录"
    width="500px"
    :close-on-click-modal="false"
    @close="handleClose"
  >
    <!-- 顶部按钮区域 -->
    <div class="top-actions">
      <el-button 
        type="success" 
        size="small" 
        @click="openContract"
        :disabled="!rental"
      >
        <el-icon><Document /></el-icon>
        租赁合同
      </el-button>
      <el-button 
        type="warning" 
        size="small" 
        @click="openShippingOrder"
        :disabled="!rental"
      >
        <el-icon><Box /></el-icon>
        发货单
      </el-button>
    </div>
    <!-- 数据加载状态提示 -->
    <div v-if="loadingLatestData" class="loading-tip">
      <el-icon class="is-loading"><Loading /></el-icon>
      正在获取最新数据...
    </div>
    
    <!-- 错误提示 -->
    <div v-if="latestDataError" class="error-tip">
      <el-icon><Warning /></el-icon>
      {{ latestDataError }}
    </div>
    <el-form
      ref="formRef"
      :model="form"
      :rules="rules"
      label-width="120px"
      v-if="rental"
    >
      <el-form-item label="设备名称" prop="deviceId">
        <el-select
          v-model="form.deviceId"
          placeholder="选择设备"
          style="width: 100%"
          @change="handleDeviceChange"
          :loading="loadingDevices"
        >
          <el-option
            v-for="device in availableDevices"
            :key="device.id"
            :label="`${device.name} (${device.serial_number || '无序列号'})`"
            :value="device.id"
            :disabled="device.conflicted"
          >
            <div style="display: flex; justify-content: space-between; align-items: center;">
              <span>{{ device.name }}</span>
              <div style="font-size: 12px; color: #999;">
                <span v-if="device.serial_number">{{ device.serial_number }}</span>
                <el-tag v-if="device.conflicted" type="danger" size="small" style="margin-left: 8px;">
                  时间冲突
                </el-tag>
              </div>
            </div>
          </el-option>
        </el-select>
        <div class="form-tip">选择不同设备会检查时间冲突</div>
      </el-form-item>

      <el-form-item label="闲鱼 ID">
        <el-input :value="rental.customer_name" disabled />
      </el-form-item>

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

      <!-- 附件选择 -->
      <el-form-item label="附件选择" prop="selectedAccessoryId">
        <div class="device-selection">
          <el-select
            v-model="form.selectedControllerId"
            placeholder="选择附件或查找可用附件"
            clearable
            filterable
            style="flex: 1"
          >
            <el-option
              v-for="controller in availableControllers"
              :key="controller.id"
              :label="controller.name"
              :value="controller.id"
            >
              <span>{{ controller.name }}</span>
              <span style="float: right; color: var(--el-text-color-secondary); font-size: 13px">
                {{ controller.model }}
              </span>
            </el-option>
          </el-select>
          <el-button
            type="info"
            @click="findAvailableAccessory"
            :loading="searchingAccessory"
            style="margin-left: 8px"
          >
            查找附件
          </el-button>
        </div>
        <div class="form-tip">选择具体附件或点击查找附件自动匹配可用附件</div>
        
        <!-- 查找到的附件信息 -->
        <div v-if="availableAccessorySlot" class="slot-info" style="margin-top: 12px">
          <div class="slot-device">
            <el-icon><Monitor /></el-icon>
            已找到可用附件: {{ availableAccessorySlot.accessory?.name || '未知附件' }}
          </div>
          <div class="slot-times">
            <div class="slot-time">
              <el-icon><Upload /></el-icon>
              寄出: {{ formatDateTime(availableAccessorySlot.shipOutDate) }}
            </div>
            <div class="slot-time">
              <el-icon><Download /></el-icon>
              收回: {{ formatDateTime(availableAccessorySlot.shipInDate) }}
            </div>
          </div>
        </div>
        
        <!-- 当前选择的附件显示 -->
        <div v-if="currentControllers.length > 0" class="current-controllers">
          <div class="current-controllers-label">当前附件：</div>
          <el-tag 
            v-for="controller in currentControllers" 
            :key="controller.id"
            type="success"
            closable
            @close="removeController(controller.id)"
            style="margin-right: 8px; margin-top: 4px;"
          >
            {{ controller.name }} {{ controller.model ? '(' + controller.model + ')' : '' }}
          </el-tag>
        </div>
      </el-form-item>
      
      <!-- 快递查询结果显示 -->
      <div v-if="trackingResults.shipOut" class="tracking-result">
        <h4>寄出快递状态</h4>
        <div class="tracking-info">
          <div class="status-item">
            <span class="label">状态：</span>
            <el-tag :type="getStatusTagType(trackingResults.shipOut.status)">
              {{ getStatusText(trackingResults.shipOut.status) }}
            </el-tag>
          </div>
          <div v-if="trackingResults.shipOut.last_update" class="status-item">
            <span class="label">最后更新：</span>
            <span>{{ trackingResults.shipOut.last_update }}</span>
          </div>
          <div v-if="trackingResults.shipOut.delivered_time" class="status-item">
            <span class="label">送达时间：</span>
            <span>{{ trackingResults.shipOut.delivered_time }}</span>
          </div>
        </div>
        <div v-if="trackingResults.shipOut.routes && trackingResults.shipOut.routes.length > 0" class="routes-list">
          <div class="route-item" v-for="(route, index) in trackingResults.shipOut.routes.slice(0, 3)" :key="index">
            <div class="route-time">{{ route.accept_time }}</div>
            <div class="route-desc">{{ route.remark }}</div>
            <div class="route-location">{{ route.accept_address }}</div>
          </div>
          <el-button 
            v-if="trackingResults.shipOut.routes.length > 3"
            type="text" 
            size="small" 
            @click="showAllRoutes('shipOut')"
          >
            查看完整路由 (共{{ trackingResults.shipOut.routes.length }}条)
          </el-button>
        </div>
      </div>
      
      <div v-if="trackingResults.shipIn" class="tracking-result">
        <h4>寄回快递状态</h4>
        <div class="tracking-info">
          <div class="status-item">
            <span class="label">状态：</span>
            <el-tag :type="getStatusTagType(trackingResults.shipIn.status)">
              {{ getStatusText(trackingResults.shipIn.status) }}
            </el-tag>
          </div>
          <div v-if="trackingResults.shipIn.last_update" class="status-item">
            <span class="label">最后更新：</span>
            <span>{{ trackingResults.shipIn.last_update }}</span>
          </div>
          <div v-if="trackingResults.shipIn.delivered_time" class="status-item">
            <span class="label">送达时间：</span>
            <span>{{ trackingResults.shipIn.delivered_time }}</span>
          </div>
        </div>
        <div v-if="trackingResults.shipIn.routes && trackingResults.shipIn.routes.length > 0" class="routes-list">
          <div class="route-item" v-for="(route, index) in trackingResults.shipIn.routes.slice(0, 3)" :key="index">
            <div class="route-time">{{ route.accept_time }}</div>
            <div class="route-desc">{{ route.remark }}</div>
            <div class="route-location">{{ route.accept_address }}</div>
          </div>
          <el-button 
            v-if="trackingResults.shipIn.routes.length > 3"
            type="text" 
            size="small" 
            @click="showAllRoutes('shipIn')"
          >
            查看完整路由 (共{{ trackingResults.shipIn.routes.length }}条)
          </el-button>
        </div>
      </div>
    </el-form>

    <template #footer>
      <div class="dialog-footer">
        <div class="left-actions">
          <el-button 
            type="danger" 
            @click="handleDelete"
            :loading="deleting"
            :disabled="!rental"
          >
            <el-icon><Delete /></el-icon>
            删除租赁
          </el-button>
        </div>
        <div class="right-actions">
          <el-button @click="handleClose">取消</el-button>
          <el-button
            type="primary"
            @click="handleSubmit"
            :loading="submitting"
          >
            保存修改
          </el-button>
        </div>
      </div>
    </template>
  </el-dialog>
  
</template>

<script setup lang="ts">
import { ref, reactive, computed, watch } from 'vue'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import { useGanttStore, type Rental } from '../stores/gantt'
import { Loading, Warning, Document, Box, Delete, Search, WarningFilled } from '@element-plus/icons-vue'
import dayjs from 'dayjs'
import VueDatePicker from '@vuepic/vue-datepicker'
import '@vuepic/vue-datepicker/dist/main.css'

const props = defineProps<{
  modelValue: boolean
  rental: Rental | null
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  'success': []
}>()

const ganttStore = useGanttStore()

// 响应式状态
const formRef = ref<FormInstance>()
const submitting = ref(false)
const deleting = ref(false)
const loadingLatestData = ref(false)
const latestDataError = ref<string | null>(null)
const queryingShipOut = ref(false)
const queryingShipIn = ref(false)
const loadingDevices = ref(false)
const availableDevices = ref<any[]>([])
const searchingAccessory = ref(false)
const availableAccessorySlot = ref<{ accessory: any; shipOutDate: Date; shipInDate: Date } | null>(null)

// 快递查询结果
const trackingResults = reactive({
  shipOut: null as any,
  shipIn: null as any
})

// 表单数据
const form = reactive({
  deviceId: null as number | null,
  endDate: null as Date | null,
  customerPhone: '',
  destination: '',
  shipOutTrackingNo: '',
  shipInTrackingNo: '',
  shipOutTime: null as Date | null,
  shipInTime: null as Date | null,
  selectedControllerId: null as number | null,
  accessories: [] as number[]
})

// 计算属性
const dialogVisible = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value)
})

const minSelectableDate = computed(() => {
  if (!props.rental?.start_date) return null
  return parseDateOnly(props.rental.start_date)
})

// 获取所有手柄设备
const availableControllers = computed(() => {
  return ganttStore.devices?.filter(device => 
    device.is_accessory && device.model && device.model.includes('controller')
  ) || []
})


// 当前已选择的手柄
const currentControllers = computed(() => {
  return availableControllers.value.filter(controller => 
    form.accessories.includes(controller.id)
  )
})

// 表单验证规则
const rules: FormRules = {
  deviceId: [
    { required: true, message: '请选择设备', trigger: 'change' }
  ],
  endDate: [
    { required: true, message: '请选择结束日期', trigger: 'change' }
  ],
  customerPhone: [
    { pattern: /^1[3-9]\d{9}$/, message: '请输入正确的手机号码', trigger: 'blur' }
  ]
}

// 日期处理函数 - 将日期字符串转换为Date对象（仅日期，无时间）
const parseDateOnly = (dateString: string): Date | null => {
  if (!dateString) return null
  try {
    // 方法1: 使用dayjs解析（可能有时区问题）
    // const parsed = dayjs(dateString).toDate()
    
    // 方法2: 手动构造避免时区偏移
    const [year, month, day] = dateString.split('-').map(Number)
    const parsed = new Date(year, month - 1, day, 12, 0, 0) // 设置为中午12点避免时区问题
    
    console.log('原始日期字符串:', dateString)
    console.log('解析结果:', parsed)
    console.log('解析后的日期显示:', parsed.toLocaleDateString('zh-CN'))
    console.log('年月日:', parsed.getFullYear(), parsed.getMonth() + 1, parsed.getDate())
    
    return parsed
  } catch (error) {
    console.error('日期处理错误:', error)
    return null
  }
}


// 时间变化处理函数 - VueDatePicker 返回 Date 对象
const handleEndDateChange = (value: Date | null) => {
  console.log('=== 结束日期变化 ===')
  console.log('选择的 Date 对象:', value)
  if (value) {
    console.log('格式化后的日期:', dayjs(value).format('YYYY-MM-DD'))
    console.log('本地时间显示:', value.toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' }))
  }
  form.endDate = value
}

const handleShipOutTimeChange = (value: Date | null) => {
  console.log('=== 寄出时间变化 ===')
  console.log('选择的 Date 对象:', value)
  if (value) {
    console.log('格式化后的时间:', dayjs(value).format('YYYY-MM-DD HH:mm:ss'))
    console.log('本地时间显示:', value.toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' }))
  }
  form.shipOutTime = value
}

const handleShipInTimeChange = (value: Date | null) => {
  console.log('=== 收回时间变化 ===')
  console.log('选择的 Date 对象:', value)
  if (value) {
    console.log('格式化后的时间:', dayjs(value).format('YYYY-MM-DD HH:mm:ss'))
    console.log('本地时间显示:', value.toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' }))
  }
  form.shipInTime = value
}

// 转换数据库时间字符串为本地 Date 对象（数据库存储的就是东八区时间）
const parseDateTime = (dateTimeString: string): Date | null => {
  if (!dateTimeString) return null
  try {
    // 移除可能的时区信息和毫秒
    const cleanString = dateTimeString.replace(/[TZ]/g, ' ').replace(/\.\d+/, '').trim()
    console.log('清理后的时间字符串:', cleanString)
    
    // 解析日期和时间部分
    const parts = cleanString.split(' ')
    const [year, month, day] = parts[0].split('-').map(Number)
    const [hour, minute, second] = (parts[1] || '00:00:00').split(':').map(Number)
    
    // 创建一个 Date 对象，表示我们想要在 VueDatePicker 中显示的时间
    // 不管用户在什么时区，都要显示数据库中存储的数字
    
    // 获取当前系统时区偏移量（分钟）
    const systemOffset = new Date().getTimezoneOffset()
    
    // 如果系统时区不是东八区，需要调整
    if (systemOffset !== -480) { // -480 表示东八区（UTC+8）
      // 创建一个 UTC 时间，然后减去系统偏移，让本地显示为期望的数字
      const utcTime = Date.UTC(year, month - 1, day, hour, minute, second)
      const adjustedTime = utcTime - (systemOffset * 60 * 1000)
      const result = new Date(adjustedTime)
      
      console.log('系统时区偏移:', systemOffset, '分钟')
      console.log('调整后的 Date:', result.toString())
      console.log('显示的小时:', result.getHours())
      
      return result
    } else {
      // 系统就是东八区，直接创建
      const localDate = new Date(year, month - 1, day, hour, minute, second)
      console.log('东八区环境，直接创建 Date:', localDate.toString())
      return localDate
    }
  } catch (error) {
    console.error('解析日期时间错误:', error)
    return null
  }
}

// 加载所有设备并检查冲突
const loadDevicesWithConflictCheck = async (rental: Rental) => {
  loadingDevices.value = true
  try {
    const devices = ganttStore.devices
    const conflictCheckPromises = devices.map(async (device) => {
      // 检查当前设备是否与其他租赁有时间冲突
      const hasConflict = await checkDeviceConflict(
        device.id, 
        rental.start_date, 
        rental.end_date, 
        rental.id // 排除当前租赁
      )
      return {
        ...device,
        conflicted: hasConflict
      }
    })
    
    availableDevices.value = await Promise.all(conflictCheckPromises)
  } catch (error) {
    console.error('加载设备列表失败:', error)
    ElMessage.error('加载设备列表失败')
  } finally {
    loadingDevices.value = false
  }
}

// 检查设备时间冲突
const checkDeviceConflict = async (deviceId: number, startDate: string, endDate: string, excludeRentalId?: number) => {
  try {
    const response = await fetch('/api/rentals/check-conflict', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        device_id: deviceId,
        start_date: startDate,
        end_date: endDate,
        exclude_rental_id: excludeRentalId
      })
    })
    
    const result = await response.json()
    return result.has_conflict || false
  } catch (error) {
    console.error('检查设备冲突失败:', error)
    return false
  }
}

// 加载最新数据的函数
const loadLatestRentalData = async (rental: Rental) => {
  loadingLatestData.value = true
  latestDataError.value = null
  
  try {
    // 实时获取最新的rental数据
    const latestRental = await ganttStore.getRentalById(rental.id)
    if (latestRental) {
      // 使用最新数据更新表单，确保日期格式正确 - 统一使用Date对象
      
      form.deviceId = latestRental.device_id
      form.endDate = parseDateOnly(latestRental.end_date)
      form.customerPhone = latestRental.customer_phone || ''
      form.destination = latestRental.destination || ''
      form.shipOutTrackingNo = latestRental.ship_out_tracking_no || ''
      form.shipInTrackingNo = latestRental.ship_in_tracking_no || ''
      // 转换数据库时间字符串为 Date 对象，用于 VueDatePicker
      form.shipOutTime = parseDateTime(latestRental.ship_out_time || '')
      form.shipInTime = parseDateTime(latestRental.ship_in_time || '')
      
      // 加载附件信息（从child_rentals中获取）
      form.accessories = (latestRental as any).child_rentals?.map((childRental: any) => childRental.device_id) || []
      
      console.log('加载的寄出时间:', latestRental.ship_out_time, '-> Date:', form.shipOutTime)
      console.log('加载的收回时间:', latestRental.ship_in_time, '-> Date:', form.shipInTime)
      
      // 额外的调试信息
      if (form.shipOutTime) {
        console.log('shipOutTime 详细信息:')
        console.log('  年:', form.shipOutTime.getFullYear())
        console.log('  月:', form.shipOutTime.getMonth() + 1)
        console.log('  日:', form.shipOutTime.getDate())
        console.log('  时:', form.shipOutTime.getHours())
        console.log('  分:', form.shipOutTime.getMinutes())
        console.log('  toString():', form.shipOutTime.toString())
        console.log('  toISOString():', form.shipOutTime.toISOString())
      }
      
      if (form.shipInTime) {
        console.log('shipInTime 详细信息:')
        console.log('  年:', form.shipInTime.getFullYear())
        console.log('  月:', form.shipInTime.getMonth() + 1)
        console.log('  日:', form.shipInTime.getDate())
        console.log('  时:', form.shipInTime.getHours())
        console.log('  分:', form.shipInTime.getMinutes())
        console.log('  toString():', form.shipInTime.toString())
        console.log('  toISOString():', form.shipInTime.toISOString())
      }
      
      console.log('=== 日期调试信息 ===')
      console.log('API返回的end_date:', latestRental.end_date)
      console.log('API返回的start_date:', latestRental.start_date)
      console.log('格式化后的endDate:', form.endDate)
      console.log('form.endDate类型:', typeof form.endDate)
      console.log('form.endDate值:', form.endDate)
      console.log('====================')
    } else {
      // 如果获取失败，使用传入的数据
      form.deviceId = rental.device_id
      form.endDate = parseDateOnly(rental.end_date)
      form.customerPhone = rental.customer_phone || ''
      form.destination = rental.destination || ''
      form.shipOutTrackingNo = rental.ship_out_tracking_no || ''
      form.shipInTrackingNo = rental.ship_in_tracking_no || ''
      // 转换数据库时间字符串为 Date 对象
      form.shipOutTime = parseDateTime(rental.ship_out_time || '')
      form.shipInTime = parseDateTime(rental.ship_in_time || '')
      
      // 加载附件信息（使用缓存数据，从child_rentals中获取）
      form.accessories = (rental as any).child_rentals?.map((childRental: any) => childRental.device_id) || []
      
      latestDataError.value = '获取最新数据失败，使用缓存数据'
    }
  } catch (error) {
    // 出错时使用传入的数据
    form.deviceId = rental.device_id
    form.endDate = parseDateOnly(rental.end_date)
    form.customerPhone = rental.customer_phone || ''
    form.destination = rental.destination || ''
    form.shipOutTrackingNo = rental.ship_out_tracking_no || ''
    form.shipInTrackingNo = rental.ship_in_tracking_no || ''
    // 转换数据库时间字符串为 Date 对象
    form.shipOutTime = parseDateTime(rental.ship_out_time || '')
    form.shipInTime = parseDateTime(rental.ship_in_time || '')
    
    // 加载附件信息（使用错误回退数据，从child_rentals中获取）
    form.accessories = (rental as any).child_rentals?.map((childRental: any) => childRental.device_id) || []
    
    latestDataError.value = '获取最新数据失败：' + (error as Error).message
  } finally {
    loadingLatestData.value = false
  }
}

// 监听对话框显示状态和租赁数据变化
watch([() => props.modelValue, () => props.rental], async ([visible, rental]) => {
  // 只有当对话框显示且有rental数据时才加载最新数据
  if (visible && rental) {
    await loadLatestRentalData(rental)
    await loadDevicesWithConflictCheck(rental)
  }
}, { immediate: true })

// 检查手柄是否可用
const isControllerAvailable = (controller: any) => {
  if (!props.rental) return true
  
  // 检查该手柄在指定时间段是否被租赁
  const rentals = ganttStore.getRentalsForDevice(controller.id)
  
  // 使用租赁的寄出和收回时间进行检查
  let startTime: Date | null = null
  let endTime: Date | null = null
  
  if (form.shipOutTime && form.shipInTime) {
    startTime = form.shipOutTime
    endTime = form.shipInTime
  } else if (props.rental.ship_out_time && props.rental.ship_in_time) {
    startTime = parseDateTime(props.rental.ship_out_time)
    endTime = parseDateTime(props.rental.ship_in_time)
  } else {
    // 如果没有具体时间，使用默认的寄出收回时间
    const startDate = new Date(props.rental.start_date)
    const endDate = new Date(props.rental.end_date)
    startTime = new Date(startDate.getTime() - 24 * 60 * 60 * 1000) // 提前一天寄出
    endTime = new Date(endDate.getTime() + 24 * 60 * 60 * 1000) // 延后一天收回
  }
  
  if (!startTime || !endTime) return true
  
  const hasConflict = rentals.some(rental => {
    if (rental.id === props.rental?.id) return false // 排除当前租赁
    
    let rentalStart: Date | null = null
    let rentalEnd: Date | null = null
    
    if (rental.ship_out_time && rental.ship_in_time) {
      rentalStart = new Date(rental.ship_out_time)
      rentalEnd = new Date(rental.ship_in_time)
    } else {
      // 使用默认时间
      const rStartDate = new Date(rental.start_date)
      const rEndDate = new Date(rental.end_date)
      rentalStart = new Date(rStartDate.getTime() - 24 * 60 * 60 * 1000)
      rentalEnd = new Date(rEndDate.getTime() + 24 * 60 * 60 * 1000)
    }
    
    return (
      rental.status === 'active' &&
      ((startTime >= rentalStart && startTime <= rentalEnd) ||
       (endTime >= rentalStart && endTime <= rentalEnd) ||
       (startTime <= rentalStart && endTime >= rentalEnd))
    )
  })
  
  return !hasConflict
}


// 添加手柄
const addController = () => {
  if (form.selectedControllerId && !form.accessories.includes(form.selectedControllerId)) {
    form.accessories.push(form.selectedControllerId)
    form.selectedControllerId = null
  }
}

// 移除手柄
const removeController = (controllerId: number) => {
  form.accessories = form.accessories.filter(id => id !== controllerId)
}

// 查找可用附件
const findAvailableAccessory = async () => {
  if (!props.rental) {
    ElMessage.warning('请先选择要编辑的租赁记录')
    return
  }

  searchingAccessory.value = true
  try {
    // 使用统一的find-slot接口查找手柄附件
    const result = await ganttStore.findAvailableSlot(
      props.rental.start_date,
      props.rental.end_date,
      Math.ceil((new Date(props.rental.ship_out_time || '').getTime() - new Date(props.rental.start_date).getTime()) / (24 * 60 * 60 * 1000)) || 1,
      '%controller%'  // 查找包含controller的设备型号
    )

    if (!result.device) {
      throw new Error('在指定时间段内没有可用的手柄附件')
    }

    // 设置查找到的附件信息
    availableAccessorySlot.value = {
      accessory: result.device,
      shipOutDate: result.shipOutDate,
      shipInDate: result.shipInDate
    }

    // 自动选择找到的附件
    form.selectedControllerId = result.device.id
    
    ElMessage.success(`找到可用附件: ${result.device.name}`)
  } catch (error) {
    console.error('查找附件失败:', error)
    ElMessage.error((error as Error).message)
    availableAccessorySlot.value = null
  } finally {
    searchingAccessory.value = false
  }
}

// 格式化日期时间显示
const formatDateTime = (date: Date) => {
  return date.toLocaleString('zh-CN', {
    month: 'numeric',
    day: 'numeric', 
    hour: '2-digit',
    minute: '2-digit'
  })
}

// 监听选择的手柄ID变化，自动添加到附件列表
watch(() => form.selectedControllerId, (newId) => {
  if (newId) {
    addController()
  }
})

// 设备变更处理函数
const handleDeviceChange = async (deviceId: number) => {
  if (!props.rental || !deviceId) return
  
  // 重新检查所选设备的冲突状态
  const hasConflict = await checkDeviceConflict(
    deviceId, 
    props.rental.start_date, 
    props.rental.end_date, 
    props.rental.id
  )
  
  if (hasConflict) {
    ElMessage.warning('所选设备在当前时间段有冲突，请检查时间安排')
  }
  
  // 如果寄出时间或寄回时间发生变化，重新检查冲突
  if (form.shipOutTime || form.shipInTime) {
    await recheckDeviceConflicts()
  }
}

// 重新检查所有设备的冲突状态
const recheckDeviceConflicts = async () => {
  if (!props.rental) return
  
  loadingDevices.value = true
  try {
    const updatedDevices = await Promise.all(
      availableDevices.value.map(async (device) => {
        const hasConflict = await checkDeviceConflict(
          device.id,
          props.rental!.start_date,
          props.rental!.end_date,
          props.rental!.id
        )
        return {
          ...device,
          conflicted: hasConflict
        }
      })
    )
    availableDevices.value = updatedDevices
  } catch (error) {
    console.error('重新检查设备冲突失败:', error)
  } finally {
    loadingDevices.value = false
  }
}


const handleSubmit = async () => {
  if (!props.rental) return

  try {
    await formRef.value?.validate()
  } catch {
    return
  }

  submitting.value = true
  try {
    // 将Date对象转换为字符串格式发送给后端，确保使用本地日期
    const endDateString = form.endDate ? 
      dayjs(form.endDate).format('YYYY-MM-DD') : 
      ''
    
    const updateData = {
      device_id: form.deviceId,
      end_date: endDateString,
      customer_phone: form.customerPhone,
      destination: form.destination,
      ship_out_tracking_no: form.shipOutTrackingNo,
      ship_in_tracking_no: form.shipInTrackingNo,
      ship_out_time: form.shipOutTime ? dayjs(form.shipOutTime).format('YYYY-MM-DD HH:mm:ss') : '',
      ship_in_time: form.shipInTime ? dayjs(form.shipInTime).format('YYYY-MM-DD HH:mm:ss') : '',
      accessories: form.accessories
    }
    
    console.log('提交的end_date:', endDateString)
    console.log('原始Date对象:', form.endDate)

    await ganttStore.updateRental(props.rental.id, updateData)
    emit('success')
    handleClose()
  } catch (error) {
    ElMessage.error('更新失败：' + (error as Error).message)
  } finally {
    submitting.value = false
  }
}

// 删除租赁记录
const handleDelete = async () => {
  if (!props.rental) return
  
  try {
    // 确认删除
    await ElMessageBox.confirm(
      `确定要删除租赁记录吗？\n\n设备：${props.rental.device_name}\n客户：${props.rental.customer_name}\n时间段：${props.rental.start_date} 至 ${props.rental.end_date}\n\n删除后无法恢复！`,
      '确认删除',
      {
        type: 'warning',
        confirmButtonText: '确认删除',
        cancelButtonText: '取消',
        dangerouslyUseHTMLString: false
      }
    )
    
    deleting.value = true
    
    // 调用删除API
    await ganttStore.deleteRental(props.rental.id)
    
    ElMessage.success('租赁记录已删除')
    emit('success')
    handleClose()
    
  } catch (error: any) {
    if (error !== 'cancel') {
      ElMessage.error('删除失败：' + (error.message || '未知错误'))
    }
  } finally {
    deleting.value = false
  }
}

// 跳转方法 - 新开页面
const openContract = () => {
  if (props.rental) {
    window.open(`/contract/${props.rental.id}`, '_blank')
  }
}

const openShippingOrder = () => {
  if (props.rental) {
    window.open(`/shipping/${props.rental.id}`, '_blank')
  }
}

// 快递查询相关方法
const queryShipOutTracking = async () => {
  if (!form.shipOutTrackingNo?.trim()) return
  
  queryingShipOut.value = true
  try {
    const response = await fetch('/api/tracking/query', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        tracking_number: form.shipOutTrackingNo.trim()
      })
    })
    
    const result = await response.json()
    
    if (result.success) {
      trackingResults.shipOut = result.tracking_info
      ElMessage.success('查询成功')
    } else {
      ElMessage.error(result.message || '查询失败')
    }
  } catch (error) {
    ElMessage.error('查询失败：' + (error as Error).message)
  } finally {
    queryingShipOut.value = false
  }
}

const queryShipInTracking = async () => {
  if (!form.shipInTrackingNo?.trim()) return
  
  queryingShipIn.value = true
  try {
    const response = await fetch('/api/tracking/query', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        tracking_number: form.shipInTrackingNo.trim()
      })
    })
    
    const result = await response.json()
    
    if (result.success) {
      trackingResults.shipIn = result.tracking_info
      ElMessage.success('查询成功')
      
      // 如果是寄回快递且已送达，更新ship_in_time
      if (result.tracking_info.is_delivered && result.tracking_info.delivered_time && props.rental) {
        try {
          await ganttStore.updateRental(props.rental.id, {
            ship_in_time: result.tracking_info.delivered_time
          })
          ElMessage.success('已自动更新寄回时间')
        } catch (error) {
          console.error('更新寄回时间失败:', error)
        }
      }
    } else {
      ElMessage.error(result.message || '查询失败')
    }
  } catch (error) {
    ElMessage.error('查询失败：' + (error as Error).message)
  } finally {
    queryingShipIn.value = false
  }
}

// 状态标签类型
const getStatusTagType = (status: string) => {
  switch (status) {
    case 'delivered':
      return 'success'
    case 'delivering':
    case 'in_transit':
      return 'warning'
    case 'picked_up':
      return 'info'
    case 'not_found':
      return 'danger'
    default:
      return ''
  }
}

// 状态文本
const getStatusText = (status: string) => {
  switch (status) {
    case 'delivered':
      return '已送达'
    case 'delivering':
      return '派送中'
    case 'in_transit':
      return '运输中'
    case 'picked_up':
      return '已收件'
    case 'processing':
      return '处理中'
    case 'not_found':
      return '未找到'
    default:
      return '未知状态'
  }
}

// 显示完整路由
const showAllRoutes = (type: 'shipOut' | 'shipIn') => {
  const routes = trackingResults[type]?.routes || []
  if (routes.length === 0) return
  
  const routeText = routes.map((route: any) => 
    `${route.accept_time}\n${route.remark}\n${route.accept_address}`
  ).join('\n\n')
  
  ElMessageBox.alert(routeText, `完整路由信息 (${routes.length}条)`, {
    confirmButtonText: '确定',
    type: 'info',
    dangerouslyUseHTMLString: false
  })
}

const handleClose = () => {
  formRef.value?.resetFields()
  submitting.value = false
  deleting.value = false
  loadingLatestData.value = false
  latestDataError.value = null
  queryingShipOut.value = false
  queryingShipIn.value = false
  
  // 清空表单数据
  form.deviceId = null
  form.endDate = null
  form.customerPhone = ''
  form.destination = ''
  form.shipOutTrackingNo = ''
  form.shipInTrackingNo = ''
  form.shipOutTime = null
  form.shipInTime = null
  form.selectedControllerId = null
  form.accessories = []
  
  // 清空快递查询结果
  trackingResults.shipOut = null
  trackingResults.shipIn = null
  
  emit('update:modelValue', false)
}
</script>

<style scoped>
.top-actions {
  display: flex;
  gap: 12px;
  margin-bottom: 20px;
  padding-bottom: 15px;
  border-bottom: 1px solid var(--el-border-color-light);
  justify-content: flex-end;
}

.form-tip {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-top: 4px;
}

.dialog-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.left-actions {
  display: flex;
  gap: 8px;
}

.right-actions {
  display: flex;
  gap: 12px;
}

.loading-tip {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px;
  background: var(--el-color-info-light-9);
  border-radius: 4px;
  margin-bottom: 16px;
  color: var(--el-color-info);
  font-size: 14px;
}

.error-tip {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px;
  background: var(--el-color-error-light-9);
  border-radius: 4px;
  margin-bottom: 16px;
  color: var(--el-color-error);
  font-size: 14px;
}

.tracking-input-group {
  display: flex;
  align-items: center;
  width: 100%;
}

.tracking-result {
  margin-top: 16px;
  padding: 16px;
  border: 1px solid var(--el-border-color-light);
  border-radius: 4px;
  background: var(--el-bg-color-page);
}

.tracking-result h4 {
  margin: 0 0 12px 0;
  font-size: 14px;
  color: var(--el-text-color-primary);
}

.tracking-info {
  margin-bottom: 12px;
}

.status-item {
  display: flex;
  align-items: center;
  margin-bottom: 8px;
}

.status-item .label {
  font-weight: 500;
  margin-right: 8px;
  min-width: 80px;
}

.routes-list {
  border-top: 1px solid var(--el-border-color-lighter);
  padding-top: 12px;
}

.route-item {
  padding: 8px 0;
  border-bottom: 1px solid var(--el-border-color-lighter);
}

.route-item:last-child {
  border-bottom: none;
}

.route-time {
  font-weight: 500;
  color: var(--el-text-color-primary);
  font-size: 12px;
  margin-bottom: 4px;
}

.route-desc {
  color: var(--el-text-color-primary);
  font-size: 13px;
  margin-bottom: 2px;
}

.route-location {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.controller-section {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 4px;
  padding: 12px;
  background-color: var(--el-fill-color-lighter);
}

.controller-available {
  color: var(--el-color-success);
  font-size: 12px;
  margin-left: 8px;
}

.controller-unavailable {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 8px;
  color: var(--el-color-error);
  font-size: 12px;
}

.controller-selection {
  margin-top: 8px;
}

.current-controllers {
  margin-top: 12px;
}

.current-controllers-label {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-bottom: 4px;
}

.device-selection {
  display: flex;
  align-items: center;
  width: 100%;
}

.slot-info {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.slot-device {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 500;
  color: var(--el-color-success);
}

.slot-times {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 14px;
}

.slot-time {
  display: flex;
  align-items: center;
  gap: 4px;
  color: var(--el-text-color-regular);
}
</style>
