import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import axios from 'axios'
import {
  getCurrentDate,
  toDateString,
  DateRangeUtils,
  formatDisplayDate
} from '@/utils/dateUtils'
import dayjs from 'dayjs'

export interface Device {
  id: number
  name: string
  serial_number: string
  status: 'idle' | 'pending_ship' | 'renting' | 'pending_return' | 'returned' | 'offline'
  created_at: string
  updated_at: string
}

export interface Rental {
  id: number
  device_id: number
  device_name: string
  start_date: string
  end_date: string
  customer_name: string
  customer_phone: string
  destination: string
  ship_out_tracking_no?: string
  ship_in_tracking_no?: string
  status: string
  ship_out_time?: string
  ship_in_time?: string
}

export interface AvailableSlot {
  device: Device
  shipOutDate: Date
  shipInDate: Date
}

export const useGanttStore = defineStore('gantt', () => {
  // 状态
  const devices = ref<Device[]>([])
  const rentals = ref<Rental[]>([])
  const currentDate = ref(getCurrentDate().toDate())
  const loading = ref(false)
  const error = ref<string | null>(null)

  // 计算属性
  const dateRange = computed(() => {
    const range = DateRangeUtils.getWeekRange(dayjs(currentDate.value))
    return { start: range.start.toDate(), end: range.end.toDate() }
  })

  const currentPeriod = computed(() => {
    const { start, end } = dateRange.value
    const startStr = formatDisplayDate(start, 'YYYY年MM月DD日')
    const endStr = formatDisplayDate(end, 'YYYY年MM月DD日')
    const startDay = getCurrentDate().startOf('day')
    const endDay = getCurrentDate().add(30, 'day').startOf('day')
    const totalDays = endDay.diff(startDay, 'day') + 1
    return `${startStr} - ${endStr} (共${totalDays}天)`
  })

  const availableDevices = computed(() => {
    return devices.value.filter(device => device.status === 'idle')
  })

  // 获取指定设备的租赁记录
  const getRentalsForDevice = (deviceId: number): Rental[] => {
    return rentals.value.filter(rental => rental.device_id === deviceId)
  }

  // 方法
  const loadData = async () => {
    loading.value = true
    error.value = null
    
    try {
      const response = await axios.get('/api/gantt/data', {
        params: {
          start_date: toDateString(dateRange.value.start),
          end_date: toDateString(dateRange.value.end)
        }
      })
      
      if (response.data.success) {
        devices.value = response.data.data.devices
        rentals.value = response.data.data.rentals
      } else {
        throw new Error(response.data.error || '加载数据失败')
      }
    } catch (err: any) {
      error.value = err.message
      console.error('加载数据失败:', err)
    } finally {
      loading.value = false
    }
  }

  const navigateWeek = (weeks: number) => {
    currentDate.value = dayjs(currentDate.value).add(weeks * 7, 'day').toDate()
    loadData()
  }

  const navigateToMonth = (months: number) => {
    currentDate.value = dayjs(currentDate.value).add(months, 'month').toDate()
    loadData()
  }

  const goToToday = () => {
    currentDate.value = getCurrentDate().toDate()
    loadData()
  }

  const findAvailableSlot = async (startDate: string, endDate: string, logisticsDays: number) => {
    try {
      const response = await axios.post('/api/rentals/find-slot', {
        start_date: startDate,
        end_date: endDate,
        logistics_days: logisticsDays
      })

      if (response.data.success) {
        const data = response.data.data
        return {
          device: data.device,
          shipOutDate: new Date(data.ship_out_date),
          shipInDate: new Date(data.ship_in_date),
          message: response.data.message || '找到可用档期'
        }
      } else {
        throw new Error(response.data.error || '查找档期失败')
      }
    } catch (err: any) {
      throw new Error(err.response?.data?.error || err.message || '查找档期失败')
    }
  }

  const createRental = async (rentalData: any) => {
    try {
      console.log('=== 前端发送创建租赁请求 ===')
      console.log('完整请求数据:', rentalData)
      console.log('ship_out_time 值:', rentalData.ship_out_time)
      console.log('ship_in_time 值:', rentalData.ship_in_time)
      console.log('ship_out_time 类型:', typeof rentalData.ship_out_time)
      console.log('ship_in_time 类型:', typeof rentalData.ship_in_time)
      
      const response = await axios.post('/api/rentals', rentalData)
      
      console.log('后端响应:', response.data)
      
      if (response.data.success) {
        await loadData() // 重新加载数据
        return response.data
      } else {
        throw new Error(response.data.error || '创建租赁失败')
      }
    } catch (err: any) {
      console.error('创建租赁失败:', err)
      throw new Error(err.response?.data?.error || err.message || '创建租赁失败')
    }
  }

  const updateRental = async (rentalId: number, updateData: any) => {
    try {
      const response = await axios.put(`/web/rentals/${rentalId}`, updateData)
      if (response.data.success) {
        await loadData()
        return response.data
      } else {
        throw new Error(response.data.error || '更新租赁失败')
      }
    } catch (err: any) {
      throw new Error(err.response?.data?.error || err.message || '更新租赁失败')
    }
  }

  const deleteRental = async (rentalId: number) => {
    try {
      const response = await axios.delete(`/web/rentals/${rentalId}`)
      if (response.data.success) {
        await loadData()
        return response.data
      } else {
        throw new Error(response.data.error || '删除租赁失败')
      }
    } catch (err: any) {
      throw new Error(err.response?.data?.error || err.message || '删除租赁失败')
    }
  }

  // 获取单个rental的最新数据
  const getRentalById = async (rentalId: number): Promise<Rental | null> => {
    try {
      const response = await axios.get(`/api/rentals/${rentalId}`)
      if (response.data.success) {
        return response.data.data
      } else {
        throw new Error(response.data.error || '获取租赁数据失败')
      }
    } catch (err: any) {
      console.error('获取租赁数据失败:', err)
      return null
    }
  }

  // 更新设备状态
  const updateDeviceStatus = async (deviceId: number, status: string) => {
    try {
      const response = await axios.put(`/api/devices/${deviceId}`, {
        status: status
      })
      
      if (response.data.success) {
        // 更新本地设备状态
        const device = devices.value.find(d => d.id === deviceId)
        if (device) {
          device.status = status as Device['status']
        }
        return response.data
      } else {
        throw new Error(response.data.error || '更新设备状态失败')
      }
    } catch (err: any) {
      throw new Error(err.response?.data?.error || err.message || '更新设备状态失败')
    }
  }

  // 添加设备
  const addDevice = async (deviceData: { name: string; serial_number: string; description?: string }) => {
    try {
      const response = await axios.post('/api/devices', {
        name: deviceData.name,
        serial_number: deviceData.serial_number,
        status: 'idle'
      })
      
      if (response.data.success) {
        await loadData() // 重新加载数据以显示新设备
        return response.data
      } else {
        throw new Error(response.data.error || '添加设备失败')
      }
    } catch (err: any) {
      throw new Error(err.response?.data?.error || err.message || '添加设备失败')
    }
  }

  return {
    // 状态
    devices,
    rentals,
    currentDate,
    loading,
    error,
    
    // 计算属性
    dateRange,
    currentPeriod,
    availableDevices,
    
    // 方法
    getRentalsForDevice,
    loadData,
    navigateWeek,
    navigateToMonth,
    goToToday,
    findAvailableSlot,
    createRental,
    updateRental,
    deleteRental,
    getRentalById,
    updateDeviceStatus,
    addDevice
  }
})
