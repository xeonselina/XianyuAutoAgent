import { computed, ref } from 'vue'
import axios from 'axios'

import type { PendingReturn } from '@/types/pendingReturn'

const errorMessage = (error: any, fallback: string) => (
  error.response?.data?.message
  || error.response?.data?.error
  || error.message
  || fallback
)

export const usePendingReturns = () => {
  const rentals = ref<PendingReturn[]>([])
  const loading = ref(false)
  const updatingIds = ref<Set<number>>(new Set())
  const returnedIds = new Set<number>()
  const count = computed(() => rentals.value.length)

  const load = async () => {
    loading.value = true
    try {
      const response = await axios.get('/api/rentals/pending-returns')
      if (!response.data.success) {
        throw new Error(
          response.data.message
          || response.data.error
          || '获取待归还列表失败',
        )
      }
      const loadedRentals: PendingReturn[] = response.data.data?.rentals || []
      rentals.value = loadedRentals.filter(
        (rental) => !returnedIds.has(rental.id),
      )
    } catch (error: any) {
      throw new Error(errorMessage(error, '获取待归还列表失败'))
    } finally {
      loading.value = false
    }
  }

  const markReturned = async (rentalId: number) => {
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
