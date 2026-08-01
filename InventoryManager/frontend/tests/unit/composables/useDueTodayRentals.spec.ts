import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { DueTodayRental } from '@/types/dueTodayRental'
import { useDueTodayRentals } from '@/composables/useDueTodayRentals'

const { axiosGet, axiosPut } = vi.hoisted(() => ({
  axiosGet: vi.fn(),
  axiosPut: vi.fn(),
}))

vi.mock('axios', () => ({
  default: {
    get: axiosGet,
    put: axiosPut,
  },
}))

const dueRental: DueTodayRental = {
  id: 7,
  device_model: 'iPhone 15 Pro',
  start_date: '2026-07-25',
  end_date: '2026-07-28',
  destination: '上海市浦东新区测试路 1 号',
  customer_phone: '13800138000',
  status: 'shipped',
}

const dueTodayResponse = (rentals: DueTodayRental[]) => ({
  data: {
    success: true,
    data: {
      rentals,
      count: rentals.length,
    },
  },
})

describe('useDueTodayRentals', () => {
  beforeEach(() => {
    axiosGet.mockReset()
    axiosPut.mockReset()
  })

  it('loads the complete due-today list', async () => {
    axiosGet.mockResolvedValueOnce(dueTodayResponse([dueRental]))
    const state = useDueTodayRentals()

    await state.load()

    expect(axiosGet).toHaveBeenCalledWith('/api/rentals/due-today')
    expect(state.rentals.value).toEqual([dueRental])
    expect(state.count.value).toBe(1)
    expect(state.loading.value).toBe(false)
  })

  it('marks one rental returned and reloads the list', async () => {
    axiosGet
      .mockResolvedValueOnce(dueTodayResponse([dueRental]))
      .mockResolvedValueOnce(dueTodayResponse([]))
    axiosPut.mockResolvedValueOnce({
      data: { success: true, data: { id: dueRental.id, status: 'returned' } },
    })
    const state = useDueTodayRentals()
    await state.load()

    const update = state.markReturned(dueRental.id)
    expect(state.updatingIds.value.has(dueRental.id)).toBe(true)
    await update

    expect(axiosPut).toHaveBeenCalledWith(
      `/api/rentals/${dueRental.id}/status`,
      { status: 'returned' },
    )
    expect(axiosGet).toHaveBeenCalledTimes(2)
    expect(state.rentals.value).toEqual([])
    expect(state.count.value).toBe(0)
    expect(state.updatingIds.value.has(dueRental.id)).toBe(false)
  })

  it('keeps the row and clears its loading state when update fails', async () => {
    axiosGet.mockResolvedValueOnce(dueTodayResponse([dueRental]))
    axiosPut.mockRejectedValueOnce({
      response: { data: { message: '状态已变化' } },
    })
    const state = useDueTodayRentals()
    await state.load()

    await expect(state.markReturned(dueRental.id)).rejects.toThrow(
      '状态已变化',
    )

    expect(state.rentals.value).toEqual([dueRental])
    expect(state.updatingIds.value.has(dueRental.id)).toBe(false)
  })

  it('keeps a successful update when the follow-up reload fails', async () => {
    axiosGet
      .mockResolvedValueOnce(dueTodayResponse([dueRental]))
      .mockRejectedValueOnce(new Error('刷新失败'))
    axiosPut.mockResolvedValueOnce({
      data: { success: true, data: { id: dueRental.id, status: 'returned' } },
    })
    const state = useDueTodayRentals()
    await state.load()

    await expect(state.markReturned(dueRental.id)).resolves.toBeUndefined()

    expect(state.rentals.value).toEqual([])
    expect(state.count.value).toBe(0)
    expect(state.updatingIds.value.has(dueRental.id)).toBe(false)
  })
})
