/**
 * 设备管理组合式函数
 * 提供设备和附件的加载、管理功能
 */
import { ref } from 'vue'
import { useGanttStore } from '@/stores/gantt'
import type { Device, DeviceModel } from '@/stores/gantt'
import axios from 'axios'

export interface DeviceWithStatus extends Device {
  conflicted?: boolean
  isAvailable?: boolean
  conflictReason?: string
}

export function useDeviceManagement() {
  const ganttStore = useGanttStore()

  const loading = ref(false)
  const devices = ref<DeviceWithStatus[]>([])
  const accessories = ref<DeviceWithStatus[]>([])
  const deviceModels = ref<DeviceModel[]>([])

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
    loading.value = true
    try {
      const response = await axios.get('/api/devices')
      if (response.data.success) {
        accessories.value = response.data.data
          .filter((device: Device) => device.is_accessory && device.model)
          .map((device: Device) => ({ ...device }))
      }
    } catch (error) {
      console.error('加载附件列表失败:', error)
      throw error
    } finally {
      loading.value = false
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
