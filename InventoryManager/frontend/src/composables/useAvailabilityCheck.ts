/**
 * 可用性检查组合式函数
 * 提供设备和附件的可用性检查和状态管理
 */
import { ref, type Ref } from 'vue'
import { useConflictDetection } from './useConflictDetection'
import type { DeviceWithStatus } from './useDeviceManagement'

export interface AvailabilityState {
  checked: boolean
  availableItems: DeviceWithStatus[]
  unavailableItems: DeviceWithStatus[]
}

export function useAvailabilityCheck() {
  const { checkMultipleDevicesConflict } = useConflictDetection()

  const deviceAvailability = ref<AvailabilityState>({
    checked: false,
    availableItems: [],
    unavailableItems: []
  })

  const accessoryAvailability = ref<AvailabilityState>({
    checked: false,
    availableItems: [],
    unavailableItems: []
  })

  const checking = ref(false)

  /**
   * 检查设备列表的可用性
   */
  const checkDevicesAvailability = async (
    devices: DeviceWithStatus[],
    params: {
      startDate: string | Date
      endDate: string | Date
      logisticsDays?: number
      excludeRentalId?: number
    }
  ) => {
    if (!devices.length) {
      deviceAvailability.value = {
        checked: true,
        availableItems: [],
        unavailableItems: []
      }
      return
    }

    checking.value = true
    try {
      const deviceIds = devices.map(d => d.id)
      const conflicts = await checkMultipleDevicesConflict(deviceIds, params)

      const available: DeviceWithStatus[] = []
      const unavailable: DeviceWithStatus[] = []

      devices.forEach(device => {
        const hasConflict = conflicts[device.id]
        const deviceWithStatus = {
          ...device,
          conflicted: hasConflict,
          isAvailable: !hasConflict
        }

        if (hasConflict) {
          unavailable.push(deviceWithStatus)
        } else {
          available.push(deviceWithStatus)
        }
      })

      deviceAvailability.value = {
        checked: true,
        availableItems: available,
        unavailableItems: unavailable
      }
    } catch (error) {
      console.error('检查设备可用性失败:', error)
      deviceAvailability.value = {
        checked: true,
        availableItems: [],
        unavailableItems: devices
      }
    } finally {
      checking.value = false
    }
  }

  /**
   * 检查附件列表的可用性
   */
  const checkAccessoriesAvailability = async (
    accessories: DeviceWithStatus[],
    params: {
      startDate: string | Date
      endDate: string | Date
      excludeRentalId?: number
    }
  ) => {
    if (!accessories.length) {
      accessoryAvailability.value = {
        checked: true,
        availableItems: [],
        unavailableItems: []
      }
      return
    }

    checking.value = true
    try {
      const accessoryIds = accessories.map(a => a.id)
      const conflicts = await checkMultipleDevicesConflict(accessoryIds, params)

      const available: DeviceWithStatus[] = []
      const unavailable: DeviceWithStatus[] = []

      accessories.forEach(accessory => {
        const hasConflict = conflicts[accessory.id]
        const accessoryWithStatus = {
          ...accessory,
          conflicted: hasConflict,
          isAvailable: !hasConflict,
          conflictReason: hasConflict ? '档期冲突' : undefined
        }

        if (hasConflict) {
          unavailable.push(accessoryWithStatus)
        } else {
          available.push(accessoryWithStatus)
        }
      })

      accessoryAvailability.value = {
        checked: true,
        availableItems: available,
        unavailableItems: unavailable
      }
    } catch (error) {
      console.error('检查附件可用性失败:', error)
      accessoryAvailability.value = {
        checked: true,
        availableItems: [],
        unavailableItems: accessories
      }
    } finally {
      checking.value = false
    }
  }

  /**
   * 判断设备是否可用
   */
  const isDeviceAvailable = (deviceId: number) => {
    return deviceAvailability.value.availableItems.some(d => d.id === deviceId)
  }

  /**
   * 判断附件是否可用
   */
  const isAccessoryAvailable = (accessoryId: number) => {
    return accessoryAvailability.value.availableItems.some(a => a.id === accessoryId)
  }

  /**
   * 重置设备可用性状态
   */
  const resetDeviceAvailability = () => {
    deviceAvailability.value = {
      checked: false,
      availableItems: [],
      unavailableItems: []
    }
  }

  /**
   * 重置附件可用性状态
   */
  const resetAccessoryAvailability = () => {
    accessoryAvailability.value = {
      checked: false,
      availableItems: [],
      unavailableItems: []
    }
  }

  /**
   * 重置所有可用性状态
   */
  const resetAll = () => {
    resetDeviceAvailability()
    resetAccessoryAvailability()
  }

  return {
    checking,
    deviceAvailability,
    accessoryAvailability,
    checkDevicesAvailability,
    checkAccessoriesAvailability,
    isDeviceAvailable,
    isAccessoryAvailable,
    resetDeviceAvailability,
    resetAccessoryAvailability,
    resetAll
  }
}
