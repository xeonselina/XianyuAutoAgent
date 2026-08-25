import { computed, ref } from 'vue'
import axios from 'axios'

import type { PendingReturn } from '@/types/pendingReturn'
import { useTenantStore } from '@/stores/tenant'

const errorMessage = (error: any, fallback: string) => (
  error.response?.data?.message
  || error.response?.data?.error
  || error.message
  || fallback
)

export const usePendingReturns = () => {
  const tenantStore = useTenantStore()
  const rentals = ref<PendingReturn[]>([])
  const loading = ref(false)
  const updatingIds = ref<Set<number>>(new Set())
  const returnedIds = new Set<number>()
  const knownWarehouseByRental = new Map<number, number>()
  let loadedWarehouseId: number | 'all' | undefined
  let loadGeneration = 0
  const count = computed(() => rentals.value.length)

  const load = async () => {
    const requestGeneration = ++loadGeneration
    loading.value = true
    rentals.value = []
    updatingIds.value = new Set()
    if (loadedWarehouseId !== tenantStore.currentWarehouseId) {
      knownWarehouseByRental.clear()
    }
    let warehouseId: number | 'all' | undefined
    try {
      await tenantStore.initialize()
      if (requestGeneration !== loadGeneration) return
      warehouseId = tenantStore.currentWarehouseId
      const response = await axios.get('/api/rentals/pending-returns', {
        params: { warehouse_id: warehouseId },
      })
      if (!response.data.success) {
        throw new Error(
          response.data.message
          || response.data.error
          || '获取待归还列表失败',
        )
      }
      const loadedRentals: PendingReturn[] = response.data.data?.rentals || []
      if (
        requestGeneration === loadGeneration
        && warehouseId === tenantStore.currentWarehouseId
      ) {
        rentals.value = loadedRentals.filter(
          (rental) => !returnedIds.has(rental.id),
        )
        loadedWarehouseId = warehouseId
        knownWarehouseByRental.clear()
        loadedRentals.forEach((rental) => {
          knownWarehouseByRental.set(rental.id, rental.warehouse_id)
        })
      }
    } catch (error: any) {
      if (
        requestGeneration !== loadGeneration
        || (warehouseId !== undefined && warehouseId !== tenantStore.currentWarehouseId)
      ) return
      throw new Error(errorMessage(error, '获取待归还列表失败'))
    } finally {
      if (requestGeneration === loadGeneration) loading.value = false
    }
  }

  const markReturned = async (rentalId: number) => {
    const warehouseId = tenantStore.requireConcreteWarehouse()
    const rental = rentals.value.find((row) => row.id === rentalId)
    const entityWarehouseId = rental?.warehouse_id
      ?? (loadedWarehouseId === warehouseId
        ? knownWarehouseByRental.get(rentalId)
        : undefined)
    if (entityWarehouseId !== warehouseId) {
      throw new Error('记录不属于当前仓库')
    }
    if (updatingIds.value.has(rentalId)) return

    updatingIds.value = new Set(updatingIds.value).add(rentalId)
    try {
      let response
      try {
        response = await axios.put(`/api/rentals/${rentalId}/status`, {
          status: 'returned',
        })
      } catch (error: any) {
        throw new Error(errorMessage(error, '更新租赁状态失败'))
      }

      if (!response.data.success) {
        throw new Error(
          response.data.message
          || response.data.error
          || '更新租赁状态失败',
        )
      }

      returnedIds.add(rentalId)
      rentals.value = rentals.value.filter((rental) => rental.id !== rentalId)
      try {
        await load()
      } catch {
        // 状态已成功更新时保留本地移除结果，避免误报更新失败。
      }
    } finally {
      const nextUpdatingIds = new Set(updatingIds.value)
      nextUpdatingIds.delete(rentalId)
      updatingIds.value = nextUpdatingIds
    }
  }

  return {
    rentals,
    count,
    loading,
    updatingIds,
    load,
    markReturned,
  }
}
