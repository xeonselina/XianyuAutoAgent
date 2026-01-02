/**
 * 甘特图 Store
 * 管理设备、租赁数据和视图状态
 */

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import dayjs from 'dayjs'
import { getGanttData } from '@/api/gantt'
import { getDevices } from '@/api/device'
import { getRentals } from '@/api/rental'
import type { GanttDevice, Device, Rental, GanttData } from '@/types'
import { showToast } from 'vant'

export const useGanttStore = defineStore('gantt', () => {
  // State
  const devices = ref<GanttDevice[]>([])
  const allDevices = ref<Device[]>([])
  const rentals = ref<Rental[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)

  // 当前查看的日期范围
  const currentStartDate = ref(dayjs().format('YYYY-MM-DD'))
  const currentEndDate = ref(dayjs().add(14, 'day').format('YYYY-MM-DD'))

  // 选中的日期 (用于高亮显示)
  const selectedDate = ref<string | null>(null)

  // 搜索关键词
  const searchKeyword = ref('')

  // Computed
  
  /**
   * 过滤后的设备列表(根据搜索关键词)
   */
  const filteredDevices = computed(() => {
    if (!searchKeyword.value) {
      return devices.value
    }
    
    const keyword = searchKeyword.value.toLowerCase()
    return devices.value.filter(device => {
      // 搜索设备名称、型号
      const deviceMatch = 
        device.name.toLowerCase().includes(keyword) ||
        device.model.toLowerCase().includes(keyword) ||
        device.serial_number.toLowerCase().includes(keyword)
      
      // 搜索租赁客户名称
      const rentalMatch = device.rentals.some(rental => 
        rental.customer_name.toLowerCase().includes(keyword)
      )
      
      return deviceMatch || rentalMatch
    })
  })

  /**
   * 获取指定设备的租赁记录
   */
  const getDeviceRentals = (deviceId: number) => {
    const device = devices.value.find(d => d.id === deviceId)
    return device?.rentals || []
  }

  /**
   * 加载甘特图数据
   */
  const loadGanttData = async (startDate?: string, endDate?: string) => {
    loading.value = true
    error.value = null
    
    try {
      const params = {
        start_date: startDate || currentStartDate.value,
        end_date: endDate || currentEndDate.value
      }
      
      const response = await getGanttData(params) as any
      
      if (response.success) {
        const data: GanttData = response.data
        devices.value = data.devices
        rentals.value = data.rentals
        
        // 更新日期范围
        if (data.date_range) {
          currentStartDate.value = data.date_range.start
          currentEndDate.value = data.date_range.end
        }
      } else {
        throw new Error(response.error || '加载甘特图数据失败')
      }
    } catch (err: any) {
      error.value = err.message || '网络请求失败'
      showToast({
        message: error.value || '网络请求失败',
        position: 'top'
      })
      console.error('Failed to load gantt data:', err)
    } finally {
      loading.value = false
    }
  }

  /**
   * 加载所有设备列表
   */
  const loadDevices = async () => {
    try {
      const response = await getDevices() as any
      
      if (response.success) {
        allDevices.value = response.data
      } else {
        throw new Error(response.error || '加载设备列表失败')
      }
    } catch (err: any) {
      showToast({
        message: err.message || '加载设备失败',
        position: 'top'
      })
      console.error('Failed to load devices:', err)
    }
  }

  /**
   * 加载所有租赁记录
   */
  const loadRentals = async () => {
    try {
      const response = await getRentals() as any
      
      if (response.success) {
        rentals.value = response.data
      } else {
        throw new Error(response.error || '加载租赁记录失败')
      }
    } catch (err: any) {
      showToast({
        message: err.message || '加载租赁记录失败',
        position: 'top'
      })
      console.error('Failed to load rentals:', err)
    }
  }

  /**
   * 刷新数据 (甘特图 + 设备 + 租赁)
   */
  const refreshData = async () => {
    await Promise.all([
      loadGanttData(),
      loadDevices(),
      loadRentals()
    ])
  }

  /**
   * 前往今天
   */
  const goToToday = () => {
    currentStartDate.value = dayjs().format('YYYY-MM-DD')
    currentEndDate.value = dayjs().add(14, 'day').format('YYYY-MM-DD')
    loadGanttData()
  }

  /**
   * 导航到上一周
   */
  const navigatePreviousWeek = () => {
    currentStartDate.value = dayjs(currentStartDate.value).subtract(7, 'day').format('YYYY-MM-DD')
    currentEndDate.value = dayjs(currentEndDate.value).subtract(7, 'day').format('YYYY-MM-DD')
    loadGanttData()
  }

  /**
   * 导航到下一周
   */
  const navigateNextWeek = () => {
    currentStartDate.value = dayjs(currentStartDate.value).add(7, 'day').format('YYYY-MM-DD')
    currentEndDate.value = dayjs(currentEndDate.value).add(7, 'day').format('YYYY-MM-DD')
    loadGanttData()
  }

  /**
   * 跳转到指定日期
   */
  const jumpToDate = (date: string) => {
    currentStartDate.value = date
    currentEndDate.value = dayjs(date).add(14, 'day').format('YYYY-MM-DD')
    selectedDate.value = date
    loadGanttData()
  }

  /**
   * 设置选中的日期
   */
  const setSelectedDate = (date: string | null) => {
    selectedDate.value = date
  }

  /**
   * 设置搜索关键词
   */
  const setSearchKeyword = (keyword: string) => {
    searchKeyword.value = keyword
  }

  /**
   * 清空搜索
   */
  const clearSearch = () => {
    searchKeyword.value = ''
  }

  return {
    // State
    devices,
    allDevices,
    rentals,
    loading,
    error,
    currentStartDate,
    currentEndDate,
    selectedDate,
    searchKeyword,

    // Computed
    filteredDevices,

    // Actions
    loadGanttData,
    loadDevices,
    loadRentals,
    refreshData,
    getDeviceRentals,
    goToToday,
    navigatePreviousWeek,
    navigateNextWeek,
    jumpToDate,
    setSelectedDate,
    setSearchKeyword,
    clearSearch
  }
})
