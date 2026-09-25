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
  let deviceCheckGeneration = 0
  let accessoryCheckGeneration = 0

  const LIFECYCLE_LABELS: Record<string, string> = {
    sold: '已售出',
    damaged: '已损坏',
    decommissioned: '已停用',
    retired: '已退役'
  }

  /**
   * 检查设备列表的可用性
   * 同时检查所有设备的档期和生命周期状态，供设备下拉项分别显示。
   */
  const checkDevicesAvailability = async (
    devices: DeviceWithStatus[],
    params: {
      startDate: string | Date
      endDate: string | Date
      logisticsDays?: number
      excludeRentalId?: number
      shipOutTime?: string | Date
      shipInTime?: string | Date
    }
  ) => {
    const checkGeneration = ++deviceCheckGeneration
    if (!devices.length) {
      if (checkGeneration !== deviceCheckGeneration) return
      deviceAvailability.value = {
        checked: true,
        availableItems: [],
        unavailableItems: []
      }
      return
    }

    checking.value = true
    try {
      const conflicts = await checkMultipleDevicesConflict(devices.map(d => d.id), params)
      const available: DeviceWithStatus[] = []
      const unavailable: DeviceWithStatus[] = []
      devices.forEach(device => {
        const lifecycle = (device as any).lifecycle_status || 'active'
        const hasConflict = conflicts[device.id] === true
        const deviceWithStatus = {
          ...device,
          conflicted: hasConflict,
          isAvailable: lifecycle === 'active' && !hasConflict,
          conflictReason: lifecycle === 'active' ? undefined : (LIFECYCLE_LABELS[lifecycle] || lifecycle)
        }
        if (deviceWithStatus.isAvailable) available.push(deviceWithStatus)
        else unavailable.push(deviceWithStatus)
      })

      if (checkGeneration !== deviceCheckGeneration) return
      deviceAvailability.value = {
        checked: true,
        availableItems: available,
        unavailableItems: unavailable
      }
    } catch (error) {
      if (checkGeneration !== deviceCheckGeneration) return
      console.error('检查设备可用性失败:', error)
      deviceAvailability.value = {
        checked: false,
        availableItems: [],
        unavailableItems: []
      }
    } finally {
      if (checkGeneration === deviceCheckGeneration) {
        checking.value = false
      }
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
    const checkGeneration = accessoryCheckGeneration
    if (!accessories.length) {
      if (checkGeneration !== accessoryCheckGeneration) return
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

      if (checkGeneration !== accessoryCheckGeneration) return
      accessoryAvailability.value = {
        checked: true,
        availableItems: available,
        unavailableItems: unavailable
      }
    } catch (error) {
      if (checkGeneration !== accessoryCheckGeneration) return
      console.error('检查附件可用性失败:', error)
      accessoryAvailability.value = {
        checked: true,
        availableItems: [],
        unavailableItems: accessories
      }
    } finally {
      if (checkGeneration === accessoryCheckGeneration) {
        checking.value = false
      }
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
    deviceCheckGeneration += 1
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
    accessoryCheckGeneration += 1
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
    checking.value = false
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
