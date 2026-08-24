/**
 * 验货状态管理 Store
 */

import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { Rental } from '../types/rental'
import type { CheckItem, ChecklistItem, InspectionRecord, InspectionListParams, InspectionListResponse, InspectionWarehouse, LogicalAccessoryReceipt } from '../types/inspection'
import {
  getLatestRentalByDeviceId,
  getLatestRentalByDeviceName,
  createInspection,
  getInspectionById,
  updateInspection,
  getInspectionList
} from '../api/inspection'
import { ElMessage } from 'element-plus'

export const useInspectionStore = defineStore('inspection', () => {
  // 状态
  const loading = ref(false)
  const currentRental = ref<Rental | null>(null)
  const checklist = ref<ChecklistItem[]>([])
  const checkItems = ref<CheckItem[]>([])
  const currentInspection = ref<InspectionRecord | null>(null)
  const warehouses = ref<InspectionWarehouse[]>([])
  const selectedWarehouseId = ref<number | null>(null)
  const accessoryReceipts = ref<LogicalAccessoryReceipt[]>([])
  
  // 验货记录列表状态
  const inspectionRecords = ref<InspectionRecord[]>([])
  const pagination = ref({
    page: 1,
    per_page: 20,
    total: 0,
    pages: 0,
    has_prev: false,
    has_next: false
  })
  const filters = ref<InspectionListParams>({
    device_name: '',
    status: undefined,
    page: 1,
    per_page: 20
  })

  /**
   * 根据设备ID查询最近的租赁记录
   */
  const fetchLatestRentalByDeviceId = async (deviceId: number) => {
    loading.value = true
    try {
      const response = await getLatestRentalByDeviceId(deviceId)
      if (response.success && response.data) {
        currentRental.value = response.data.rental
        checklist.value = response.data.checklist
        warehouses.value = response.data.warehouses || []
        selectedWarehouseId.value = response.data.selected_warehouse_id ?? null
        accessoryReceipts.value = (response.data.accessory_receipts || []).map(item => ({ ...item }))

        // 初始化 checkItems（所有项默认已勾选）
        checkItems.value = response.data.checklist.map((item: ChecklistItem) => ({
          item_name: item.name,
          is_checked: item.default_checked ?? true,
          item_order: item.order
        }))

        return true
      } else {
        ElMessage.error(response.message || '获取租赁记录失败')
        return false
      }
    } catch (error: any) {
      const errorMsg = error.response?.data?.message || error.message || '获取租赁记录失败'
      ElMessage.error(errorMsg)
      return false
    } finally {
      loading.value = false
    }
  }

  /**
   * 根据设备名称查询最近的租赁记录
   */
  const fetchLatestRentalByDeviceName = async (deviceName: string) => {
    loading.value = true
    try {
      const response = await getLatestRentalByDeviceName(deviceName)
      if (response.success && response.data) {
        currentRental.value = response.data.rental
        checklist.value = response.data.checklist
        warehouses.value = response.data.warehouses || []
        selectedWarehouseId.value = response.data.selected_warehouse_id ?? null
        accessoryReceipts.value = (response.data.accessory_receipts || []).map(item => ({ ...item }))

        // 初始化 checkItems（所有项默认已勾选）
        checkItems.value = response.data.checklist.map((item: ChecklistItem) => ({
          item_name: item.name,
          is_checked: item.default_checked ?? true,
          item_order: item.order
        }))

        return true
      } else {
        ElMessage.error(response.message || '获取租赁记录失败')
        return false
      }
    } catch (error: any) {
      const errorMsg = error.response?.data?.message || error.message || '获取租赁记录失败'
      ElMessage.error(errorMsg)
      return false
    } finally {
      loading.value = false
    }
  }

  /**
   * 创建验货记录
   */
  const submitInspection = async () => {
    if (!currentRental.value) {
      ElMessage.error('未找到租赁记录')
      return false
    }
    if (warehouses.value.length > 1 && selectedWarehouseId.value === null) {
      ElMessage.error('请选择实际验货仓')
      return false
    }

    loading.value = true
    try {
      const response = await createInspection({
        rental_id: currentRental.value.id,
        device_id: currentRental.value.device_id,
        warehouse_id: selectedWarehouseId.value,
        check_items: checkItems.value.map((item) => ({
          name: item.item_name,
          is_checked: item.is_checked,
          order: item.item_order
        })),
        accessory_receipts: accessoryReceipts.value.map(item => ({
          accessory_type_id: item.accessory_type_id,
          outcome: item.outcome
        }))
      })

      if (response.success && response.data) {
        currentInspection.value = response.data

        const reassignments = response.data.accessory_reassignments || []
        const affectedRentalIds = Array.from(new Set(
          reassignments.flatMap(item => item.affected_rental_ids)
        )).sort((left, right) => left - right)
        const shortageRentalIds = Array.from(new Set(
          reassignments.flatMap(item => item.shortage_rental_ids)
        )).sort((left, right) => left - right)

        // 判断验货状态
        const status = response.data.status
        if (shortageRentalIds.length > 0) {
          ElMessage.warning(
            `验货已保存；未来订单 #${shortageRentalIds.join('、#')} 的附件仍然不足`
          )
        } else if (affectedRentalIds.length > 0) {
          ElMessage.success(
            `验货完成；已重新关联未来订单 #${affectedRentalIds.join('、#')} 的附件`
          )
        } else if (status === 'normal') {
          ElMessage.success('验货完成，状态正常')
        } else {
          ElMessage.warning('验货完成，但存在异常项')
        }

        return true
      } else {
        ElMessage.error(response.message || '提交验货记录失败')
        return false
      }
    } catch (error: any) {
      const errorMsg = error.response?.data?.message || error.message || '提交验货记录失败'
      ElMessage.error(errorMsg)
      return false
    } finally {
      loading.value = false
    }
  }

  /**
   * 获取验货记录详情
   */
  const fetchInspectionById = async (id: number) => {
    loading.value = true
    try {
      const response = await getInspectionById(id)
      if (response.success && response.data) {
        currentInspection.value = response.data
        checkItems.value = response.data.check_items.map((item: CheckItem) => ({
          id: item.id,
          inspection_record_id: item.inspection_record_id,
          item_name: item.item_name,
          is_checked: item.is_checked,
          item_order: item.item_order
        }))
        return true
      } else {
        ElMessage.error(response.message || '获取验货记录失败')
        return false
      }
    } catch (error: any) {
      const errorMsg = error.response?.data?.message || error.message || '获取验货记录失败'
      ElMessage.error(errorMsg)
      return false
    } finally {
      loading.value = false
    }
  }

  /**
   * 更新验货记录
   */
  const updateInspectionRecord = async (id: number) => {
    loading.value = true
    try {
      const response = await updateInspection(id, {
        check_items: checkItems.value
          .filter((item) => item.id)
          .map((item) => ({
            id: item.id!,
            is_checked: item.is_checked
          }))
      })

      if (response.success && response.data) {
        currentInspection.value = response.data
        ElMessage.success('验货记录已更新')
        return true
      } else {
        ElMessage.error(response.message || '更新验货记录失败')
        return false
      }
    } catch (error: any) {
      const errorMsg = error.response?.data?.message || error.message || '更新验货记录失败'
      ElMessage.error(errorMsg)
      return false
    } finally {
      loading.value = false
    }
  }

  /**
   * 重置状态
   */
  const reset = () => {
    currentRental.value = null
    checklist.value = []
    checkItems.value = []
    currentInspection.value = null
    warehouses.value = []
    selectedWarehouseId.value = null
    accessoryReceipts.value = []
  }

  /**
   * 切换检查项勾选状态
   */
  const toggleCheckItem = (index: number) => {
    if (index >= 0 && index < checkItems.value.length) {
      checkItems.value[index].is_checked = !checkItems.value[index].is_checked
    }
  }

  /**
   * 计算验货状态
   */
  const calculateStatus = () => {
    return checkItems.value.every((item) => item.is_checked) ? 'normal' : 'abnormal'
  }

  /**
   * 获取验货记录列表
   */
  const fetchInspectionRecords = async (params?: InspectionListParams) => {
    loading.value = true
    try {
      const searchParams = params || filters.value
      const response = await getInspectionList(searchParams)
      
      if (response.success && response.data) {
        inspectionRecords.value = response.data.records
        pagination.value = response.data.pagination
        return true
      } else {
        ElMessage.error(response.message || '获取验货记录列表失败')
        return false
      }
    } catch (error: any) {
      const errorMsg = error.response?.data?.message || error.message || '获取验货记录列表失败'
      ElMessage.error(errorMsg)
      return false
    } finally {
      loading.value = false
    }
  }

  /**
   * 更新筛选条件并重新获取列表
   */
  const updateFilters = async (newFilters: Partial<InspectionListParams>) => {
    filters.value = { ...filters.value, ...newFilters }
    return await fetchInspectionRecords(filters.value)
  }

  /**
   * 清空筛选条件
   */
  const clearFilters = async () => {
    filters.value = {
      device_name: '',
      status: undefined,
      page: 1,
      per_page: 20
    }
    return await fetchInspectionRecords(filters.value)
  }

  return {
    // 状态
    loading,
    currentRental,
    checklist,
    checkItems,
    currentInspection,
    warehouses,
    selectedWarehouseId,
    accessoryReceipts,
    inspectionRecords,
    pagination,
    filters,

    // 方法
    fetchLatestRentalByDeviceId,
    fetchLatestRentalByDeviceName,
    submitInspection,
    fetchInspectionById,
    updateInspectionRecord,
    fetchInspectionRecords,
    updateFilters,
    clearFilters,
    reset,
    toggleCheckItem,
    calculateStatus
  }
})
