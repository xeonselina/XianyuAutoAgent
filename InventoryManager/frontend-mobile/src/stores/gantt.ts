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

export interface DeviceModel {
  id: number
  name: string
  display_name: string
  description?: string
  is_active: boolean
  default_accessories?: any[]
  model_accessories?: ModelAccessory[]
  device_value?: number
  created_at: string
  updated_at: string
  accessories: ModelAccessory[]
}

export interface ModelAccessory {
  id: number
  model_id: number
  accessory_name: string
  accessory_description?: string
  accessory_value?: number
  is_required: boolean
  is_active: boolean
  created_at: string
  updated_at: string
}

export interface Device {
  id: number
  name: string
  serial_number: string
  model: string
  model_id?: number
  warehouse_id?: number | null
  device_model?: DeviceModel
  is_accessory: boolean
  lifecycle_status: 'active' | 'sold' | 'decommissioned' | 'damaged' | 'retired'
  lifecycle_reason?: string
  lifecycle_date?: string
  created_at: string
  updated_at: string
}

export interface Rental {
  id: number
  device_id: number
  device?: {
    id: number
    name: string
    serial_number: string
    model: string
    model_id?: number
    device_model?: DeviceModel
  }
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
  parent_rental_id?: number
  child_rentals?: Rental[]
  accessories?: { 
    id?: number
    name: string
    model?: string
    type?: string
    is_accessory?: boolean
    is_bundled: boolean
    serial_number?: string
    value?: number 
  }[]
  // 新字段：配套附件标记
  includes_handle: boolean
  includes_lens_mount: boolean
  // 代传照片标记
  photo_transfer: boolean
  // 镜头组合
  lens_combo?: 'lens_400mm' | 'lens_200mm' | 'bare' | 'lens_dual'
  xianyu_order_no?: string
  order_amount?: number
  buyer_id?: string
  damage_note?: string | null
  preferred_warehouse_id?: number | null
  logistics_days?: number | null
  logistics_estimate_origin_warehouse_id?: number | null
  customer_province?: string | null
  customer_city?: string | null
  customer_district?: string | null
  customer_address_detail?: string | null
  requested_accessory_type_ids?: number[]
  accessory_requests?: Array<{
    accessory_type_id: number
    fulfilled: boolean
  }>
  // 接力后一单由前一位客户直接寄出，不参与仓库批量发货
  is_relay_shipping?: boolean
  relay_predecessor_rental_id?: number | null
}

export interface GanttDailyStats {
  total_device_count: number
  available_count: number
  occupied_count: number
  planned_ship_out_count: number
  planned_return_count: number
  ship_out_count: number
  accessory_ship_out_count: number
}

export interface GanttModelFacet {
  model_id: number | null
  name: string
  display_name: string
  device_count: number
}

export interface RentalEditContext {
  request_id: string
  evaluated_at: string
  rental: Rental
  devices: Device[]
  legacy_device_bound_accessories: Device[]
  warehouses: Array<Record<string, any>>
  device_models: Array<Record<string, any>>
  accessory_types: Array<Record<string, any>>
  form_policy: Record<string, any>
}

export interface AvailableSlot {
  device: Device
  shipOutDate: Date
  shipInDate: Date
  availableControllers?: number[]
  controllerCount?: number
}

export const useGanttStore = defineStore('gantt', () => {
  // 状态
  const devices = ref<Device[]>([])
  const rentals = ref<Rental[]>([])
  const currentDate = ref(getCurrentDate().toDate())
  const selectedDate = ref<Date | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)
  const dailyStatsByDate = ref<Record<string, GanttDailyStats>>({})
  const modelFacets = ref<GanttModelFacet[]>([])
  const summaries = ref<Record<string, any>>({})
  const dataRevision = ref('')
  const evaluatedAt = ref('')
  const viewDeviceModelId = ref<number | null>(null)
  const viewLifecycleStatus = ref<string | null>('active')
  let loadGeneration = 0

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
    return devices.value.filter(device =>
      device.lifecycle_status === 'active' && !device.is_accessory
    )
  })

  // 获取指定设备的租赁记录
  const getRentalsForDevice = (deviceId: number): Rental[] => {
    return rentals.value.filter(rental => rental.device_id === deviceId)
  }

  // 方法
  const loadData = async () => {
    const generation = ++loadGeneration
    loading.value = true
    error.value = null
    
    try {
      const params: Record<string, string | number> = {
          start_date: toDateString(dateRange.value.start),
          end_date: toDateString(dateRange.value.end)
      }
      if (viewDeviceModelId.value != null) {
        params.device_model_id = viewDeviceModelId.value
      }
      if (viewLifecycleStatus.value) {
        params.lifecycle_status = viewLifecycleStatus.value
      }
      const response = await axios.get('/api/gantt/view', {
        params
      })
      
      if (response.data.success) {
        if (generation !== loadGeneration) return
        const data = response.data.data
        devices.value = (data.devices || []).map((device: any) => ({
          ...device,
          serial_number: device.serial_number || '',
          is_accessory: false,
          created_at: device.created_at || '',
          updated_at: device.updated_at || '',
          device_model: device.model_id == null ? undefined : {
            id: device.model_id,
            name: device.model_name || device.model || '',
            display_name: device.model_display_name || device.model_name || device.model || '',
            is_active: true,
            created_at: '',
            updated_at: '',
            accessories: []
          }
        }))
        const deviceById = new Map(
          devices.value.map(device => [device.id, device])
        )
        rentals.value = (data.rentals || []).map((rental: any) => {
          const device = deviceById.get(rental.device_id)
          return {
            ...rental,
            customer_phone: rental.customer_phone || '',
            destination: rental.destination || '',
            includes_handle: Boolean(rental.includes_handle),
            includes_lens_mount: Boolean(rental.includes_lens_mount),
            photo_transfer: Boolean(rental.photo_transfer),
            accessories: rental.accessories || [],
            device: device ? {
              id: device.id,
              name: device.name,
              serial_number: device.serial_number,
              model: device.model,
              model_id: device.model_id,
              device_model: device.device_model
            } : undefined
          }
        })
        dailyStatsByDate.value = data.daily_stats_by_date || {}
        modelFacets.value = data.model_facets || []
        summaries.value = data.summaries || {}
        dataRevision.value = data.data_revision || ''
        evaluatedAt.value = data.evaluated_at || ''
      } else {
        throw new Error(response.data.error || '加载数据失败')
      }
    } catch (err: any) {
      if (generation !== loadGeneration) return
      error.value = err.message
      console.error('加载数据失败:', err)
    } finally {
      if (generation === loadGeneration) {
        loading.value = false
      }
    }
  }

  const setViewFilters = (
    deviceModelId: number | null,
    lifecycleStatus: string | null
  ) => {
    viewDeviceModelId.value = deviceModelId
    viewLifecycleStatus.value = lifecycleStatus
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

  const jumpToDate = (date: Date) => {
    currentDate.value = date
    selectedDate.value = date
    loadData()
  }

  const setSelectedDate = (date: Date | null) => {
    selectedDate.value = date
  }

  const findAvailableSlot = async (startDate: string, endDate: string, logisticsDays: number, model: string | number, isAccessory: boolean = false) => {
    try {
      const response = await axios.post('/api/rentals/find-slot', {
        start_date: startDate,
        end_date: endDate,
        logistics_days: logisticsDays,
        model: model,
        is_accessory: isAccessory
      })

      if (response.data.success) {
        const data = response.data.data
        return {
          device: data.device,
          shipOutDate: new Date(data.ship_out_date),
          shipInDate: new Date(data.ship_in_date),
          availableControllers: data.available_controllers || [],
          availableDevices: data.available_devices || [],
          controllerCount: data.controller_count || 0,
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
        return response.data
      } else {
        throw new Error(
          response.data.message || response.data.error || '创建租赁失败'
        )
      }
    } catch (err: any) {
      console.error('创建租赁失败:', err)
      throw new Error(
        err.response?.data?.message
        || err.response?.data?.error
        || err.message
        || '创建租赁失败'
      )
    }
  }

  const updateRental = async (rentalId: number, updateData: any) => {
    try {
      const response = await axios.put(`/web/rentals/${rentalId}`, updateData)
      if (response.data.success) {
        return response.data
      } else {
        throw new Error(
          response.data.message || response.data.error || '更新租赁失败'
        )
      }
    } catch (err: any) {
      throw new Error(
        err.response?.data?.message
        || err.response?.data?.error
        || err.message
        || '更新租赁失败'
      )
    }
  }

  const deleteRental = async (rentalId: number) => {
    try {
      const response = await axios.delete(`/web/rentals/${rentalId}`)
      if (response.data.success) {
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

  const getRentalEditContext = async (
    rentalId: number
  ): Promise<RentalEditContext | null> => {
    try {
      const response = await axios.get(
        `/api/rentals/${rentalId}/edit-context`
      )
      if (response.data.success) {
        return response.data.data
      }
      throw new Error(response.data.error || '获取编辑上下文失败')
    } catch (err) {
      console.error('获取编辑上下文失败:', err)
      return null
    }
  }

  // 发货到闲鱼
  const shipRentalToXianyu = async (rentalId: number) => {
    try {
      const response = await axios.post(`/api/rentals/${rentalId}/ship-to-xianyu`)
      if (response.data.success) {
        return response.data
      } else {
        throw new Error(response.data.message || '发货到闲鱼失败')
      }
    } catch (err: any) {
      console.error('发货到闲鱼失败:', err)
      throw new Error(err.response?.data?.message || err.message || '发货到闲鱼失败')
    }
  }

  // 更新设备生命周期状态
  const updateDeviceLifecycle = async (deviceId: number, lifecycleStatus: string, reason?: string) => {
    try {
      const response = await axios.put(`/api/devices/${deviceId}/lifecycle`, {
        lifecycle_status: lifecycleStatus,
        lifecycle_reason: reason
      })
      if (response.data.success) {
        const device = devices.value.find(d => d.id === deviceId)
        if (device) {
          device.lifecycle_status = lifecycleStatus as Device['lifecycle_status']
        }
        return response.data
      } else {
        throw new Error(response.data.error || '更新生命周期状态失败')
      }
    } catch (err: any) {
      throw new Error(err.response?.data?.error || err.message || '更新生命周期状态失败')
    }
  }

  // 添加设备
  const addDevice = async (deviceData: {
    name: string;
    serial_number: string;
    model: string;
    model_id?: number;
    is_accessory: boolean;
    description?: string
  }) => {
    try {
      const response = await axios.post('/api/devices', {
        name: deviceData.name,
        serial_number: deviceData.serial_number,
        model: deviceData.model,
        model_id: deviceData.model_id,
        is_accessory: deviceData.is_accessory
      })
      
      if (response.data.success) {
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
    selectedDate,
    loading,
    error,
    dailyStatsByDate,
    modelFacets,
    summaries,
    dataRevision,
    evaluatedAt,
    viewDeviceModelId,
    viewLifecycleStatus,

    // 计算属性
    dateRange,
    currentPeriod,
    availableDevices,

    // 方法
    getRentalsForDevice,
    setViewFilters,
    loadData,
    navigateWeek,
    navigateToMonth,
    goToToday,
    jumpToDate,
    setSelectedDate,
    findAvailableSlot,
    createRental,
    updateRental,
    deleteRental,
    getRentalById,
    getRentalEditContext,
    shipRentalToXianyu,
    updateDeviceLifecycle,
    addDevice
  }
})
