/**
 * 冲突检测组合式函数（移动端版）
 */
import { ref } from 'vue'
import axios from 'axios'
import dayjs from 'dayjs'

export interface ConflictCheckParams {
  deviceId: number
  startDate: string | Date
  endDate: string | Date
  logisticsDays?: number
  excludeRentalId?: number
}

export function useConflictDetection() {
  const checking = ref(false)

  const calculateShipTimes = (startDate: string | Date, endDate: string | Date, logisticsDays: number = 1) => {
    const start = dayjs(startDate)
    const end = dayjs(endDate)
    const shipOutTime = start.subtract(logisticsDays + 1, 'day').hour(9).minute(0).second(0)
    const shipInTime = end.add(logisticsDays + 1, 'day').hour(18).minute(0).second(0)
    return {
      ship_out_time: shipOutTime.format('YYYY-MM-DD HH:mm:ss'),
      ship_in_time: shipInTime.format('YYYY-MM-DD HH:mm:ss')
    }
  }

  const checkDeviceConflict = async (params: ConflictCheckParams): Promise<boolean> => {
    try {
      const { ship_out_time, ship_in_time } = calculateShipTimes(
        params.startDate,
        params.endDate,
        params.logisticsDays || 1
      )
      const response = await axios.post('/api/rentals/check-conflict', {
        device_id: params.deviceId,
        ship_out_time,
        ship_in_time,
        exclude_rental_id: params.excludeRentalId
      })
      return response.data.success && response.data.data.has_conflicts
    } catch (error) {
      console.error('检查设备冲突失败:', error)
      return false
    }
  }

  const checkDuplicateRental = async (params: {
    customerName: string
    destination?: string
    startDate?: string
    endDate?: string
    excludeRentalId?: number
  }) => {
    try {
      const response = await axios.post('/api/rentals/check-duplicate', {
        customer_name: params.customerName,
        destination: params.destination,
        start_date: params.startDate,
        end_date: params.endDate,
        exclude_rental_id: params.excludeRentalId
      })
      if (response.data.success) {
        return {
          hasDuplicate: response.data.data.has_duplicate,
          duplicates: response.data.data.duplicates || []
        }
      }
      return { hasDuplicate: false, duplicates: [] }
    } catch (error) {
      console.error('检查重复租赁失败:', error)
      return { hasDuplicate: false, duplicates: [] }
    }
  }

  return {
    checking,
    checkDeviceConflict,
    checkDuplicateRental,
    calculateShipTimes
  }
}
