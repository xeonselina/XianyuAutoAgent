<template>
  <div class="gantt-container">
    <!-- 工具栏 -->
    <div class="toolbar">
      <el-row :gutter="16" align="middle">
        <el-col :span="8">
          <el-button-group>
            <el-button @click="ganttStore.navigateWeek(-1)">
              <el-icon><ArrowLeft /></el-icon>
              上周
            </el-button>
            <el-button @click="ganttStore.goToToday">今天</el-button>
            <el-button @click="ganttStore.navigateWeek(1)">
              下周
              <el-icon><ArrowRight /></el-icon>
            </el-button>
          </el-button-group>
        </el-col>
        
        <el-col :span="8" class="text-center">
          <span class="current-period">{{ ganttStore.currentPeriod }}</span>
        </el-col>
        
        <el-col :span="8" class="text-right">
          <el-button 
            type="success" 
            @click="showAddDeviceDialog = true"
            :icon="Plus"
          >
            添加设备
          </el-button>
          <el-button 
            type="primary" 
            @click="showBookingDialog = true"
            :icon="Plus"
          >
            预定设备
          </el-button>
          <el-button 
            @click="ganttStore.loadData()" 
            :loading="ganttStore.loading"
            :icon="Refresh"
          >
            刷新
          </el-button>
        </el-col>
      </el-row>
    </div>

    <!-- 过滤器 -->
    <div class="filters">
      <el-row :gutter="16">
        <el-col :span="4">
          <el-input
            v-model="searchKeyword"
            placeholder="搜索租赁人名/地址"
            clearable
            @input="onSearchInput"
            @clear="clearSearch"
          >
            <template #prefix>
              <el-icon><Search /></el-icon>
            </template>
          </el-input>
        </el-col>

        <el-col :span="4">
          <el-select
            v-model="selectedDeviceModel"
            placeholder="设备型号"
            clearable
            @change="applyFilters"
          >
            <el-option
              v-for="model in availableDeviceModels"
              :key="model"
              :label="model"
              :value="model"
            />
          </el-select>
        </el-col>

        <el-col :span="4">
          <el-select
            v-model="selectedDeviceType"
            placeholder="设备名称"
            clearable
            multiple
            collapse-tags
            collapse-tags-tooltip
            @change="applyFilters"
          >
            <el-option
              v-for="type in deviceTypes"
              :key="type"
              :label="type"
              :value="type"
            />
          </el-select>
        </el-col>

        <el-col :span="4">
          <el-select
            v-model="selectedStatus"
            placeholder="设备状态"
            clearable
            @change="applyFilters"
          >
            <el-option label="全部状态" value="" />
            <el-option label="在线" value="online" />
            <el-option label="离线" value="offline" />
          </el-select>
        </el-col>

        <el-col :span="4">
          <el-button @click="clearFilters">清除过滤</el-button>
        </el-col>
      </el-row>
    </div>

    <!-- 甘特图主体 -->
    <div class="gantt-main" v-loading="ganttStore.loading">
      <div class="gantt-scroll-container">
        <div class="gantt-header">
          <div class="device-header">设备</div>
          <div 
            v-for="date in dateArray" 
            :key="date.toString()"
            class="date-header"
            :class="{ 'is-today': isToday(date) }"
          >
            <div class="date-day">{{ formatDay(date) }}</div>
            <div class="date-weekday">{{ formatWeekday(date) }}</div>
            <div class="date-stats">
              <span v-if="getStatsForDate(date).available_count > 0" class="stat-available">
                {{ getStatsForDate(date).available_count }} 闲
              </span>
              <span
                v-if="getStatsForDate(date).ship_out_count > 0"
                class="stat-ship-out clickable"
                @click="filterByShipOutDate(date)"
                :title="`点击筛选 ${formatDay(date)} 需要寄出的主设备`"
              >
                {{ getStatsForDate(date).ship_out_count }} 寄
              </span>
              <span
                v-if="getStatsForDate(date).accessory_ship_out_count > 0"
                class="stat-accessory-ship-out clickable"
                @click="filterByAccessoryShipOutDate(date)"
                :title="`点击筛选 ${formatDay(date)} 需要寄出的附件`"
              >
                {{ getStatsForDate(date).accessory_ship_out_count }} 附寄
              </span>
              <span v-if="getStatsForDate(date).controller_count > 0" class="stat-controller">
                {{ getStatsForDate(date).controller_count }} 手柄
              </span>
            </div>
          </div>
        </div>

        <div class="gantt-body" ref="ganttBodyRef">
          <div
            class="virtual-container"
            :style="{ height: `${totalHeight}px` }"
          >
            <div
              class="visible-items"
              :style="{ transform: `translateY(${offsetY}px)` }"
            >
              <GanttRow
                v-for="device in visibleDevices"
                :key="device.id"
                :device="device"
                :rentals="ganttStore.getRentalsForDevice(device.id)"
                :dates="dateArray"
                @edit-rental="handleEditRental"
                @delete-rental="handleDeleteRental"
                @update-device-status="handleUpdateDeviceStatus"
              />
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 预定对话框 -->
    <BookingDialog
      v-model="showBookingDialog"
      :selected-device-model="selectedDeviceModel"
      @success="handleBookingSuccess"
    />

    <!-- 编辑租赁对话框 -->
    <EditRentalDialogNew
      v-model="showEditDialog"
      :rental="selectedRental"
      @success="handleEditSuccess"
    />

    <!-- 添加设备对话框 -->
    <el-dialog 
      v-model="showAddDeviceDialog" 
      title="添加设备" 
      width="500px"
      @close="resetAddDeviceForm"
    >
      <el-form 
        ref="addDeviceFormRef" 
        :model="addDeviceForm" 
        :rules="addDeviceRules"
        label-width="100px"
      >
        <el-form-item label="设备名称" prop="name">
          <el-input 
            v-model="addDeviceForm.name" 
            placeholder="请输入设备名称" 
            maxlength="100"
            show-word-limit
          />
        </el-form-item>
        
        <el-form-item label="序列号" prop="serial_number">
          <el-input 
            v-model="addDeviceForm.serial_number" 
            placeholder="请输入设备序列号" 
            maxlength="50"
            show-word-limit
          />
        </el-form-item>
        
        <el-form-item label="型号" prop="model_id">
          <el-select
            v-model="addDeviceForm.model_id"
            placeholder="请选择型号"
            style="width: 100%"
            @change="onModelChange"
          >
            <el-option
              v-for="model in deviceModels"
              :key="model.id"
              :label="model.display_name"
              :value="model.id"
            />
          </el-select>
        </el-form-item>

        <el-form-item
          v-if="selectedModelAccessories.length > 0"
          label="附件类型"
          prop="accessory_type"
        >
          <el-select
            v-model="addDeviceForm.accessory_type"
            placeholder="选择附件类型（可选）"
            style="width: 100%"
            clearable
            @change="onAccessoryTypeChange"
          >
            <el-option
              v-for="accessory in selectedModelAccessories"
              :key="accessory.id"
              :label="accessory.accessory_name"
              :value="accessory.accessory_name"
            />
          </el-select>
        </el-form-item>
        
        <el-form-item label="设备类型" prop="is_accessory">
          <el-checkbox v-model="addDeviceForm.is_accessory">
            附件设备（手柄等不在租赁列表中显示）
          </el-checkbox>
        </el-form-item>
        
        <el-form-item label="设备描述" prop="description">
          <el-input 
            v-model="addDeviceForm.description" 
            type="textarea"
            :rows="3"
            placeholder="请输入设备描述（可选）" 
            maxlength="500"
            show-word-limit
          />
        </el-form-item>
      </el-form>
      
      <template #footer>
        <span class="dialog-footer">
          <el-button @click="showAddDeviceDialog = false">取消</el-button>
          <el-button 
            type="primary" 
            @click="handleAddDevice"
            :loading="addingDevice"
          >
            添加设备
          </el-button>
        </span>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch, nextTick, onUnmounted } from 'vue'
import { useGanttStore, type Device, type Rental, type DeviceModel, type ModelAccessory } from '@/stores/gantt'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Refresh, ArrowLeft, ArrowRight, Search } from '@element-plus/icons-vue'
import axios from 'axios'
import GanttRow from './GanttRow.vue'
import BookingDialog from './BookingDialog.vue'
import { EditRentalDialogNew } from './rental'
import {
  toSystemDateString,
  isToday,
  formatDisplayDate,
  generateDateRange,
  getCurrentDate
} from '@/utils/dateUtils'
import dayjs from 'dayjs'

const ganttStore = useGanttStore()

// 响应式状态
const showBookingDialog = ref(false)
const showEditDialog = ref(false)
const showAddDeviceDialog = ref(false)
const selectedRental = ref<Rental | null>(null)
const searchKeyword = ref<string>('')
const selectedDeviceModel = ref<string>('')
const selectedDeviceType = ref<string[]>([])
const selectedStatus = ref('')
const dailyStats = ref<Record<string, {available_count: number, ship_out_count: number, accessory_ship_out_count: number}>>({})

// 虚拟滚动相关
const ganttBodyRef = ref<HTMLElement>()
const itemHeight = 60  // 每行高度
const visibleCount = ref(10)  // 可见行数
const scrollTop = ref(0)
const startIndex = ref(0)
const endIndex = ref(0)

// 添加设备表单
const addDeviceFormRef = ref()
const addingDevice = ref(false)
const deviceModels = ref<DeviceModel[]>([])
const selectedModelAccessories = ref<ModelAccessory[]>([])
const addDeviceForm = ref({
  name: '',
  serial_number: '',
  model: '',
  model_id: null,
  accessory_type: '',
  is_accessory: false,
  description: ''
})

const addDeviceRules = {
  name: [
    { required: true, message: '请输入设备名称', trigger: 'blur' },
    { min: 1, max: 100, message: '设备名称长度在 1 到 100 个字符', trigger: 'blur' }
  ],
  serial_number: [
    { required: true, message: '请输入序列号', trigger: 'blur' },
    { min: 1, max: 50, message: '序列号长度在 1 到 50 个字符', trigger: 'blur' }
  ],
  model_id: [
    { required: true, message: '请选择型号', trigger: 'change' }
  ],
  description: [
    { max: 500, message: '描述不能超过 500 个字符', trigger: 'blur' }
  ]
}

// 计算属性
const dateArray = computed(() => {
  return generateDateRange(
    dayjs(ganttStore.currentDate).subtract(5, 'day'),
    dayjs(ganttStore.currentDate).add(10, 'day')
  )
})

// 计算设备型号列表用于筛选
const availableDeviceModels = computed(() => {
  const models = new Set<string>()
  ganttStore.devices.forEach(device => {
    // 优先使用 device_model.display_name，如果没有则使用旧的 model 字段
    if (device.device_model?.display_name) {
      models.add(device.device_model.display_name)
    } else if (device.model && device.model.trim()) {
      models.add(device.model)
    }
  })
  return Array.from(models).sort()
})

const deviceTypes = computed(() => {
  const types = new Set<string>()
  ganttStore.devices.forEach(device => {
    // 从设备名称中提取类型（例如：iPhone 14 Pro -> iPhone）
    const type = device.name.split(' ')[0]
    types.add(type)
  })
  return Array.from(types)
})

const filteredDevices = computed(() => {
  let devices = ganttStore.devices

  // 过滤掉附件设备（手柄）
  devices = devices.filter(device => !device.is_accessory)

  // 按搜索关键词筛选（基于租赁数据）
  if (searchKeyword.value.trim()) {
    const keyword = searchKeyword.value.toLowerCase().trim()
    devices = devices.filter(device => {
      // 获取该设备的所有租赁记录
      const rentals = ganttStore.getRentalsForDevice(device.id)
      // 检查是否有租赁记录的客户名或地址包含关键词
      return rentals.some(rental => {
        const customerName = rental.customer_name?.toLowerCase() || ''
        const destination = rental.destination?.toLowerCase() || ''
        return customerName.includes(keyword) || destination.includes(keyword)
      })
    })
  }

  // 按设备型号筛选
  if (selectedDeviceModel.value) {
    devices = devices.filter(device => {
      // 优先匹配 device_model.display_name，如果没有则匹配旧的 model 字段
      const deviceModelName = device.device_model?.display_name || device.model
      return deviceModelName === selectedDeviceModel.value
    })
  }

  // 按设备名称筛选
  if (selectedDeviceType.value.length > 0) {
    devices = devices.filter(device =>
      selectedDeviceType.value.some(type => device.name.includes(type))
    )
  }

  // 按设备状态筛选
  if (selectedStatus.value) {
    devices = devices.filter(device =>
      device.status === selectedStatus.value
    )
  }

  return devices
})

// 虚拟滚动计算属性
const totalHeight = computed(() => filteredDevices.value.length * itemHeight)

const visibleDevices = computed(() => {
  const start = startIndex.value
  const end = Math.min(endIndex.value, filteredDevices.value.length)
  return filteredDevices.value.slice(start, end)
})

const offsetY = computed(() => startIndex.value * itemHeight)

// 方法
const formatDay = (date: Date) => {
  return formatDisplayDate(date, 'M.D')
}

const formatWeekday = (date: Date) => {
  const weekdays = ['日', '一', '二', '三', '四', '五', '六']
  return weekdays[date.getDay()]
}

const applyFilters = () => {
  // 过滤逻辑在计算属性中处理
}

const clearFilters = () => {
  searchKeyword.value = ''
  selectedDeviceModel.value = ''
  selectedDeviceType.value = []
  selectedStatus.value = ''
}

// 搜索相关方法
let searchTimer: number | null = null

const onSearchInput = (value: string) => {
  // 防抖处理，避免频繁搜索
  if (searchTimer) {
    clearTimeout(searchTimer)
  }

  searchTimer = setTimeout(() => {
    searchKeyword.value = value
  }, 300) // 300ms 防抖
}

const clearSearch = () => {
  searchKeyword.value = ''
  if (searchTimer) {
    clearTimeout(searchTimer)
  }
}

// 虚拟滚动相关方法
const updateVisibleRange = () => {
  if (!ganttBodyRef.value) return

  const containerHeight = ganttBodyRef.value.clientHeight
  visibleCount.value = Math.ceil(containerHeight / itemHeight) + 2 // 额外渲染2行缓冲

  startIndex.value = Math.floor(scrollTop.value / itemHeight)
  endIndex.value = Math.min(
    startIndex.value + visibleCount.value,
    filteredDevices.value.length
  )
}

const handleScroll = (event: Event) => {
  const target = event.target as HTMLElement
  scrollTop.value = target.scrollTop
  updateVisibleRange()
}

const initVirtualScroll = async () => {
  await nextTick()
  if (ganttBodyRef.value) {
    ganttBodyRef.value.addEventListener('scroll', handleScroll)
    updateVisibleRange()
  }
}

// 点击寄出数量筛选设备
const filterByShipOutDate = (date: Date) => {
  const dateStr = toSystemDateString(date)

  // 找到在该日期需要寄出的设备名称
  const devicesToShip = ganttStore.devices.filter(device => {
    if (device.is_accessory) return false // 过滤附件设备

    const rentals = ganttStore.getRentalsForDevice(device.id)
    return rentals.some(rental => {
      if (!rental.ship_out_time) return false
      const shipOutDateStr = toSystemDateString(new Date(rental.ship_out_time))
      return shipOutDateStr === dateStr
    })
  })

  // 提取设备名称的类型（前缀）用于筛选
  const deviceTypesToFilter = devicesToShip.map(device => {
    return device.name.split(' ')[0] // 获取设备名称的第一部分作为类型
  })

  // 去重并设置筛选 - 多选模式选择所有相关类型
  const uniqueDeviceTypes: string[] = [...new Set(deviceTypesToFilter)]
  if (uniqueDeviceTypes.length > 0) {
    selectedDeviceType.value = uniqueDeviceTypes
  }

  // 显示提示信息
  if (uniqueDeviceTypes.length > 0) {
    ElMessage.success(`已筛选出 ${formatDay(date)} 需要寄出的 ${devicesToShip.length} 台主设备`)
  } else {
    ElMessage.info(`${formatDay(date)} 没有需要寄出的主设备`)
  }
}

// 点击附件寄出数量筛选附件设备
const filterByAccessoryShipOutDate = (date: Date) => {
  const dateStr = toSystemDateString(date)

  // 找到在该日期需要寄出的附件设备名称
  const accessoriesToShip = ganttStore.devices.filter(device => {
    if (!device.is_accessory) return false // 只筛选附件设备

    const rentals = ganttStore.getRentalsForDevice(device.id)
    return rentals.some(rental => {
      if (!rental.ship_out_time) return false
      const shipOutDateStr = toSystemDateString(new Date(rental.ship_out_time))
      return shipOutDateStr === dateStr
    })
  })

  // 提取附件设备名称的类型（前缀）用于筛选
  const deviceTypesToFilter = accessoriesToShip.map(device => {
    return device.name.split(' ')[0] // 获取设备名称的第一部分作为类型
  })

  // 去重并设置筛选 - 多选模式选择所有相关类型
  const uniqueDeviceTypes: string[] = [...new Set(deviceTypesToFilter)]
  if (uniqueDeviceTypes.length > 0) {
    selectedDeviceType.value = uniqueDeviceTypes
  }

  // 显示提示信息
  if (uniqueDeviceTypes.length > 0) {
    ElMessage.success(`已筛选出 ${formatDay(date)} 需要寄出的 ${accessoriesToShip.length} 个附件`)
  } else {
    ElMessage.info(`${formatDay(date)} 没有需要寄出的附件`)
  }
}

const handleBookingSuccess = async () => {
  ElMessage.success('预定成功！')
  showBookingDialog.value = false

  // 重新加载数据以反映最新变化
  await ganttStore.loadData()

  // 清除缓存以确保统计数据更新
  statsCache.clear()
  await loadDailyStats()

  // 强制触发组件重新渲染，清除GanttRow中的缓存
  await nextTick()
}

const handleEditRental = (rental: Rental) => {
  selectedRental.value = rental
  showEditDialog.value = true
}

const handleEditSuccess = async () => {
  ElMessage.success('更新成功！')
  showEditDialog.value = false
  selectedRental.value = null

  // 重新加载数据以反映最新变化
  await ganttStore.loadData()

  // 清除缓存以确保统计数据更新
  statsCache.clear()
  await loadDailyStats()

  // 强制触发组件重新渲染，清除GanttRow中的缓存
  await nextTick()
}

// 加载设备型号
const loadDeviceModels = async () => {
  try {
    const response = await axios.get('/api/device-models')
    if (response.data.success) {
      deviceModels.value = response.data.data
    }
  } catch (error) {
    console.error('加载设备型号失败:', error)
    ElMessage.error('加载设备型号失败')
  }
}

// 型号选择变化处理
const onModelChange = (modelId: number) => {
  const selectedModel = deviceModels.value.find(model => model.id === modelId)
  if (selectedModel) {
    addDeviceForm.value.model = selectedModel.name
    selectedModelAccessories.value = selectedModel.accessories || []
    // 清空附件类型选择
    addDeviceForm.value.accessory_type = ''
    addDeviceForm.value.is_accessory = false
  }
}

// 附件类型选择变化处理
const onAccessoryTypeChange = (accessoryType: string) => {
  if (accessoryType) {
    addDeviceForm.value.is_accessory = true
    // 根据附件类型自动设置设备名称
    const selectedModel = deviceModels.value.find(model => model.id === addDeviceForm.value.model_id)
    if (selectedModel && !addDeviceForm.value.name) {
      addDeviceForm.value.name = accessoryType
    }
  } else {
    addDeviceForm.value.is_accessory = false
  }
}

// 添加设备相关处理函数
const resetAddDeviceForm = () => {
  addDeviceForm.value = {
    name: '',
    serial_number: '',
    model: '',
    model_id: null,
    accessory_type: '',
    is_accessory: false,
    description: ''
  }
  selectedModelAccessories.value = []
  if (addDeviceFormRef.value) {
    addDeviceFormRef.value.resetFields()
  }
}

const handleAddDevice = async () => {
  if (!addDeviceFormRef.value) return
  
  try {
    await addDeviceFormRef.value.validate()
    addingDevice.value = true
    
    // 调用API添加设备
    await ganttStore.addDevice(addDeviceForm.value)
    
    ElMessage.success('设备添加成功！')
    showAddDeviceDialog.value = false
    resetAddDeviceForm()
    
    // 重新加载数据
    await ganttStore.loadData()
  } catch (error) {
    if (typeof error === 'string') {
      // 表单验证错误
      return
    }
    ElMessage.error('添加设备失败：' + (error as Error).message)
  } finally {
    addingDevice.value = false
  }
}

const handleDeleteRental = async (rental: Rental) => {
  try {
    await ElMessageBox.confirm(
      '确定要删除这个租赁记录吗？此操作不可恢复。',
      '确认删除',
      {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        type: 'warning',
      }
    )
    
    await ganttStore.deleteRental(rental.id)
    ElMessage.success('删除成功！')

    // 重新加载数据以反映最新变化
    await ganttStore.loadData()

    // 清除缓存以确保统计数据更新
    statsCache.clear()
    await loadDailyStats()
  } catch (error) {
    if (error !== 'cancel') {
      ElMessage.error('删除失败：' + (error as Error).message)
    }
  }
}

const handleUpdateDeviceStatus = async (device: Device, newStatus: string) => {
  try {
    await ganttStore.updateDeviceStatus(device.id, newStatus)
    ElMessage.success('设备状态更新成功！')

    // 重新加载数据以反映最新变化
    await ganttStore.loadData()
  } catch (error) {
    ElMessage.error('状态更新失败：' + (error as Error).message)
    // 如果更新失败，恢复原状态
    const originalDevice = ganttStore.devices.find(d => d.id === device.id)
    if (originalDevice) {
      // 重新加载数据以确保状态同步
      await ganttStore.loadData()
    }
  }
}

// 统计数据缓存
const statsCache = new Map<string, any>()
let loadStatsTimer: number | null = null

// 获取每日统计信息（带缓存和防抖）
const loadDailyStats = async () => {
  // 防抖处理
  if (loadStatsTimer) {
    clearTimeout(loadStatsTimer)
  }

  loadStatsTimer = setTimeout(async () => {
    try {
      const cacheKey = `${selectedDeviceModel.value || 'all'}_${dateArray.value[0]?.getTime() || 0}_${dateArray.value[dateArray.value.length - 1]?.getTime() || 0}`

      // 检查缓存
      if (statsCache.has(cacheKey)) {
        dailyStats.value = statsCache.get(cacheKey)
        return
      }

      const stats = await Promise.all(
        dateArray.value.map(async (date) => {
          const dateStr = toSystemDateString(date)
          const params: any = { date: dateStr }

          // 如果选择了设备型号，添加到参数中
          if (selectedDeviceModel.value) {
            params.device_model = selectedDeviceModel.value
          }

          const response = await axios.get('/api/gantt/daily-stats', { params })

          if (response.data.success) {
            return {
              date: dateStr,
              ...response.data.data
            }
          }
          return {
            date: dateStr,
            available_count: 0,
            ship_out_count: 0,
            accessory_ship_out_count: 0
          }
        })
      )

      // 将统计数据存储到响应式对象中
      const statsMap: Record<string, {available_count: number, ship_out_count: number, accessory_ship_out_count: number}> = {}
      stats.forEach(stat => {
        statsMap[stat.date] = {
          available_count: stat.available_count,
          ship_out_count: stat.ship_out_count,
          accessory_ship_out_count: stat.accessory_ship_out_count || 0
        }
      })

      // 缓存结果
      statsCache.set(cacheKey, statsMap)

      // 限制缓存大小
      if (statsCache.size > 10) {
        const firstKey = statsCache.keys().next().value
        if (firstKey) {
          statsCache.delete(firstKey)
        }
      }

      dailyStats.value = statsMap
    } catch (error) {
      console.error('加载每日统计失败:', error)
    }
  }, 300) // 300ms 防抖
}

// 获取指定日期的统计信息
const getStatsForDate = (date: Date) => {
  const dateStr = toSystemDateString(date)
  const stats = dailyStats.value[dateStr] || { available_count: 0, ship_out_count: 0, accessory_ship_out_count: 0 }

  // 计算当日空闲手柄数量
  const controllerCount = getIdleControllerCountForDate(date)

  return {
    ...stats,
    controller_count: controllerCount
  }
}

// 计算指定日期的空闲手柄数量
const getIdleControllerCountForDate = (date: Date) => {
  // 获取所有手柄设备（is_accessory=true且model包含controller）
  const controllers = ganttStore.devices.filter(device => 
    device.is_accessory && device.model && device.model.includes('controller')
  )
  
  // 计算当日空闲的手柄数量
  let idleCount = 0
  controllers.forEach(controller => {
    // 检查该手柄在当日是否被租赁
    const rentals = ganttStore.getRentalsForDevice(controller.id)
    const dateStr = toSystemDateString(date)
    
    const isRented = rentals.some(rental => {
      const startDate = new Date(rental.start_date)
      const endDate = new Date(rental.end_date)
      return date >= startDate && date <= endDate && rental.status === 'active'
    })
    
    if (!isRented) {
      idleCount++
    }
  })
  
  return idleCount
}

// 监听日期范围变化，重新加载统计数据
watch(() => ganttStore.dateRange, () => {
  loadDailyStats()
}, { deep: true })

// 监听设备和租赁数据变化，重新加载统计数据
watch([() => ganttStore.devices, () => ganttStore.rentals], () => {
  loadDailyStats()
}, { deep: true })

// 监听设备型号列表变化，默认选择第一个型号
watch(availableDeviceModels, (newModels) => {
  if (newModels.length > 0 && !selectedDeviceModel.value) {
    selectedDeviceModel.value = newModels[0]
  }
}, { immediate: true })

// 监听设备型号筛选变化，重新加载统计数据
watch(selectedDeviceModel, () => {
  loadDailyStats()
})

// 监听设备数据变化，重新计算虚拟滚动
watch(filteredDevices, () => {
  updateVisibleRange()
}, { deep: true })

// 生命周期
onMounted(async () => {
  await Promise.all([
    ganttStore.loadData(),
    loadDailyStats(),
    loadDeviceModels()
  ])

  // 初始化虚拟滚动
  await initVirtualScroll()
})

onUnmounted(() => {
  if (ganttBodyRef.value) {
    ganttBodyRef.value.removeEventListener('scroll', handleScroll)
  }
  // 清理定时器
  if (loadStatsTimer) {
    clearTimeout(loadStatsTimer)
  }
  if (searchTimer) {
    clearTimeout(searchTimer)
  }
  // 清理缓存
  statsCache.clear()
})
</script>

<style scoped>
.gantt-container {
  padding: 20px;
  height: 100vh;
  width: 100%;
  display: flex;
  flex-direction: column;
  background: white;
  overflow: hidden;
}

.toolbar {
  margin-bottom: 20px;
}

.current-period {
  font-weight: 600;
  font-size: 16px;
  color: var(--el-text-color-primary);
}

.text-center {
  text-align: center;
}

.text-right {
  text-align: right;
}

.filters {
  margin-bottom: 20px;
  padding: 16px;
  background: var(--el-bg-color-page);
  border-radius: 8px;
}

.gantt-main {
  flex: 1;
  overflow: hidden;
  border: 1px solid var(--el-border-color);
  border-radius: 8px;
  background: white;
  width: 100%;
  height: 100%;
}

.gantt-header {
  display: flex;
  position: sticky;
  top: 0;
  z-index: 10;
  background: var(--el-bg-color);
  border-bottom: 2px solid var(--el-border-color);
  flex-shrink: 0;
}

.device-header {
  min-width: 200px;
  width: 200px;
  padding: 12px 16px;
  background: var(--el-fill-color-light);
  border-right: 1px solid var(--el-border-color);
  font-weight: 600;
  color: var(--el-text-color-primary);
  position: sticky;
  left: 0;
  z-index: 11;
  flex-shrink: 0;
}

.date-header {
  min-width: 80px;
  width: 80px;
  padding: 8px 4px;
  text-align: center;
  border-right: 1px solid var(--el-border-color-lighter);
  background: var(--el-fill-color-lighter);
  color: #1890ff;
  font-weight: 600;
}

.date-header.is-today {
  background: var(--el-color-primary-light-9);
  color: var(--el-color-primary);
  font-weight: 600;
}

.date-day {
  font-size: 14px;
  font-weight: 600;
}

.date-weekday {
  font-size: 12px;
  opacity: 0.7;
  margin-top: 2px;
}

.date-stats {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin-top: 4px;
}

.stat-available {
  font-size: 10px;
  color: #67c23a;
  font-weight: 600;
  background: rgba(103, 194, 58, 0.1);
  padding: 1px 4px;
  border-radius: 3px;
  border: 1px solid rgba(103, 194, 58, 0.3);
}

.stat-ship-out {
  font-size: 10px;
  color: #f56c6c;
  font-weight: 600;
  background: rgba(245, 108, 108, 0.1);
  padding: 1px 4px;
  border-radius: 3px;
  border: 1px solid rgba(245, 108, 108, 0.3);
}

.stat-ship-out.clickable {
  cursor: pointer;
  transition: all 0.2s ease;
}

.stat-ship-out.clickable:hover {
  background: rgba(245, 108, 108, 0.2);
  border: 1px solid rgba(245, 108, 108, 0.5);
  transform: scale(1.05);
  box-shadow: 0 2px 4px rgba(245, 108, 108, 0.3);
}

.stat-accessory-ship-out {
  font-size: 10px;
  color: #e6a23c;
  font-weight: 600;
  background: rgba(230, 162, 60, 0.1);
  padding: 1px 4px;
  border-radius: 3px;
  border: 1px solid rgba(230, 162, 60, 0.3);
}

.stat-accessory-ship-out.clickable {
  cursor: pointer;
  transition: all 0.2s ease;
}

.stat-accessory-ship-out.clickable:hover {
  background: rgba(230, 162, 60, 0.2);
  border: 1px solid rgba(230, 162, 60, 0.5);
  transform: scale(1.05);
  box-shadow: 0 2px 4px rgba(230, 162, 60, 0.3);
}

.stat-controller {
  font-size: 10px;
  color: #909399;
  font-weight: 600;
  background: rgba(144, 147, 153, 0.1);
  padding: 1px 4px;
  border-radius: 3px;
  border: 1px solid rgba(144, 147, 153, 0.3);
}

.gantt-scroll-container {
  width: 100%;
  overflow-x: auto;
  overflow-y: hidden;
  max-height: calc(100vh - 200px);
  position: relative;
  height: 100%;
  display: flex;
  flex-direction: column;
}

.gantt-body {
  min-height: 400px;
  width: 100%;
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
  position: relative;
}

.virtual-container {
  position: relative;
  width: 100%;
}

.visible-items {
  position: relative;
  width: 100%;
}

/* 确保甘特图行使用正确的布局 */
.gantt-row {
  display: flex;
  width: 100%;
  min-width: max-content;
}

/* 调试样式 - 确保滚动容器可见 */
.gantt-scroll-container::-webkit-scrollbar {
  width: 8px;
  height: 8px;
}

.gantt-scroll-container::-webkit-scrollbar-track {
  background: #f1f1f1;
  border-radius: 4px;
}

.gantt-scroll-container::-webkit-scrollbar-thumb {
  background: #c1c1c1;
  border-radius: 4px;
}

.gantt-scroll-container::-webkit-scrollbar-thumb:hover {
  background: #a8a8a8;
}
</style>
