/**
 * 设备管理组合式函数
 * 提供设备和附件的加载、管理功能
 */
import { ref } from 'vue'
import { useGanttStore } from '@/stores/gantt'
import type { Device, DeviceModel } from '@/stores/gantt'
import axios from 'axios'
import { useTenantStore } from '@/stores/tenant'

export interface DeviceWithStatus extends Device {
  conflicted?: boolean
  isAvailable?: boolean
  conflictReason?: string
}

export function useDeviceManagement() {
  const ganttStore = useGanttStore()
  const tenantStore = useTenantStore()

  const loading = ref(false)
  const devices = ref<DeviceWithStatus[]>([])
  const accessories = ref<DeviceWithStatus[]>([])
  const deviceModels = ref<DeviceModel[]>([])
  let accessoriesGeneration = 0

  /**
   * 加载所有设备（非附件）
   */
  const loadDevices = async () => {
    loading.value = true
    try {
      devices.value = ganttStore.devices
        .filter(device => !device.is_accessory)
        .map(device => ({ ...device }))
    } catch (error) {
      console.error('加载设备列表失败:', error)
      throw error
    } finally {
      loading.value = false
    }
  }

  /**
   * 加载所有附件
   */
  const loadAccessories = async () => {
    const requestGeneration = ++accessoriesGeneration
    loading.value = true
    accessories.value = []
    try {
      await tenantStore.initialize()
      if (requestGeneration !== accessoriesGeneration) return
      const warehouseId = tenantStore.currentWarehouseId
      const response = await axios.get('/api/devices', {
        params: {
          is_accessory: true,
          per_page: 100,
          warehouse_id: warehouseId,
        },
      })
      if (
        requestGeneration === accessoriesGeneration
        && warehouseId === tenantStore.currentWarehouseId
      ) {
        accessories.value = (response.data.devices || [])
          .map((device: Device) => ({ ...device }))
      }
    } catch (error) {
      if (requestGeneration !== accessoriesGeneration) return
      console.error('加载附件列表失败:', error)
      throw error
    } finally {
      if (requestGeneration === accessoriesGeneration) loading.value = false
    }
  }

  /**
   * 加载所有设备型号
   */
  const loadDeviceModels = async () => {
    loading.value = true
    try {
      const response = await axios.get('/api/device-models')
      if (response.data.success) {
        deviceModels.value = response.data.data
      }
    } catch (error) {
      console.error('加载设备型号列表失败:', error)
      throw error
    } finally {
      loading.value = false
    }
  }

  /**
   * 获取指定型号的设备
   */
  const getDevicesByModel = (modelName: string) => {
    return devices.value.filter(device =>
      device.model?.toLowerCase().includes(modelName.toLowerCase())
    )
  }

  /**
   * 获取指定型号的附件
   */
  const getAccessoriesByModel = (modelName: string) => {
    return accessories.value.filter(accessory =>
      accessory.model?.toLowerCase().includes(modelName.toLowerCase())
    )
  }

  /**
   * 根据ID获取设备
   */
  const getDeviceById = (deviceId: number) => {
    return devices.value.find(device => device.id === deviceId)
  }

  /**
   * 根据ID获取附件
   */
  const getAccessoryById = (accessoryId: number) => {
    return accessories.value.find(accessory => accessory.id === accessoryId)
  }

  return {
    loading,
    devices,
    accessories,
    deviceModels,
    loadDevices,
    loadAccessories,
    loadDeviceModels,
    getDevicesByModel,
    getAccessoriesByModel,
    getDeviceById,
    getAccessoryById
  }
}
