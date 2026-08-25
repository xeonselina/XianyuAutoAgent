import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import type { PendingReturn } from '@/types/pendingReturn'
import { usePendingReturns } from '@/composables/usePendingReturns'
import { useTenantStore } from '@/stores/tenant'

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

const pendingReturn: PendingReturn = {
  id: 7,
  warehouse_id: 1,
  device_model: 'iPhone 15 Pro',
  start_date: '2026-07-25',
  end_date: '2026-07-28',
  due_date: '2026-07-29',
  overdue_days: 3,
  destination: '上海市浦东新区测试路 1 号',
  customer_phone: '13800138000',
  status: 'shipped',
}

const secondPendingReturn: PendingReturn = {
  ...pendingReturn,
  id: 8,
  device_model: 'iPhone 16 Pro',
  due_date: '2026-07-30',
  overdue_days: 2,
}

const pendingReturnsResponse = (rentals: PendingReturn[]) => ({
  data: {
    success: true,
    data: {
      rentals,
      count: rentals.length,
    },
  },
})

describe('usePendingReturns', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    axiosGet.mockReset()
    axiosPut.mockReset()
    useTenantStore().setWarehousesForSession([{
      id: 1,
      name: '测试仓库',
      province: '广东省',
      city: '深圳市',
    }])
  })

  it('loads the complete pending-returns list', async () => {
    axiosGet.mockResolvedValueOnce(pendingReturnsResponse([pendingReturn]))
    const state = usePendingReturns()

    await state.load()

    expect(axiosGet).toHaveBeenCalledWith('/api/rentals/pending-returns', {
      params: { warehouse_id: 1 },
    })
    expect(state.rentals.value).toEqual([pendingReturn])
    expect(state.count.value).toBe(1)
    expect(state.loading.value).toBe(false)
  })

  it('blocks a direct returned-status write from the all-warehouses view', async () => {
    const tenant = useTenantStore()
    tenant.setWarehousesForSession([
      { id: 1, name: 'A 仓', province: '广东省', city: '深圳市' },
      { id: 2, name: 'B 仓', province: '浙江省', city: '杭州市' },
    ])
    tenant.selectWarehouse('all')
    const state = usePendingReturns()

    await expect(state.markReturned(7)).rejects.toThrow('请选择具体仓库')
    expect(axiosPut).not.toHaveBeenCalled()
  })

  it('clears A warehouse rows before loading B and leaves them empty on failure', async () => {
    const tenant = useTenantStore()
    tenant.setWarehousesForSession([
      { id: 1, name: 'A 仓', province: '广东省', city: '深圳市' },
      { id: 2, name: 'B 仓', province: '浙江省', city: '杭州市' },
    ])
    axiosGet
      .mockResolvedValueOnce(pendingReturnsResponse([pendingReturn]))
      .mockRejectedValueOnce(new Error('B 仓加载失败'))
    const state = usePendingReturns()
    await state.load()

    tenant.selectWarehouse(2)
    const loadB = state.load()

    expect(state.rentals.value).toEqual([])
    await expect(loadB).rejects.toThrow('B 仓加载失败')
    expect(state.rentals.value).toEqual([])
  })

  it('does not surface an old warehouse rejection after a newer load succeeds', async () => {
    let rejectA!: (reason?: any) => void
    const staleA = new Promise((_resolve, reject) => { rejectA = reject })
    const tenant = useTenantStore()
    tenant.setWarehousesForSession([
      { id: 1, name: 'A 仓', province: '广东省', city: '深圳市' },
      { id: 2, name: 'B 仓', province: '浙江省', city: '杭州市' },
    ])
    axiosGet
      .mockReturnValueOnce(staleA)
      .mockResolvedValueOnce(pendingReturnsResponse([]))
    const state = usePendingReturns()
    const loadA = state.load()
    await vi.waitFor(() => expect(axiosGet).toHaveBeenCalledOnce())
    tenant.selectWarehouse(2)
    await state.load()

    rejectA(new Error('A 仓旧请求失败'))
    await expect(loadA).resolves.toBeUndefined()
    expect(state.rentals.value).toEqual([])
    expect(state.loading.value).toBe(false)
  })

  it('blocks marking a rental from another warehouse as returned', async () => {
    const tenant = useTenantStore()
    tenant.setWarehousesForSession([
      { id: 1, name: 'A 仓', province: '广东省', city: '深圳市' },
      { id: 2, name: 'B 仓', province: '浙江省', city: '杭州市' },
    ])
    const state = usePendingReturns()
    state.rentals.value = [pendingReturn]
    tenant.selectWarehouse(2)

    await expect(state.markReturned(pendingReturn.id)).rejects.toThrow(
      '记录不属于当前仓库',
    )
    expect(axiosPut).not.toHaveBeenCalled()
  })

  it('marks one rental returned and reloads the list', async () => {
    axiosGet
      .mockResolvedValueOnce(pendingReturnsResponse([pendingReturn]))
      .mockResolvedValueOnce(pendingReturnsResponse([]))
    axiosPut.mockResolvedValueOnce({
      data: {
        success: true,
        data: { id: pendingReturn.id, status: 'returned' },
      },
    })
    const state = usePendingReturns()
    await state.load()

    const update = state.markReturned(pendingReturn.id)
    expect(state.updatingIds.value.has(pendingReturn.id)).toBe(true)
    await update

    expect(axiosPut).toHaveBeenCalledWith(
      `/api/rentals/${pendingReturn.id}/status`,
      { status: 'returned' },
    )
    expect(axiosGet).toHaveBeenCalledTimes(2)
    expect(state.rentals.value).toEqual([])
    expect(state.count.value).toBe(0)
    expect(state.updatingIds.value.has(pendingReturn.id)).toBe(false)
  })

  it('keeps the row and clears its loading state when update fails', async () => {
    axiosGet.mockResolvedValueOnce(pendingReturnsResponse([pendingReturn]))
    axiosPut.mockRejectedValueOnce({
      response: { data: { message: '状态已变化' } },
    })
    const state = usePendingReturns()
    await state.load()

    await expect(state.markReturned(pendingReturn.id)).rejects.toThrow(
      '状态已变化',
    )

    expect(state.rentals.value).toEqual([pendingReturn])
    expect(state.updatingIds.value.has(pendingReturn.id)).toBe(false)
  })

  it('keeps a successful update when the follow-up reload fails', async () => {
    axiosGet
      .mockResolvedValueOnce(pendingReturnsResponse([pendingReturn]))
      .mockRejectedValueOnce(new Error('刷新失败'))
    axiosPut.mockResolvedValueOnce({
      data: {
        success: true,
        data: { id: pendingReturn.id, status: 'returned' },
      },
    })
    const state = usePendingReturns()
    await state.load()

    await expect(
      state.markReturned(pendingReturn.id),
    ).resolves.toBeUndefined()

    expect(state.rentals.value).toEqual([])
    expect(state.count.value).toBe(0)
    expect(state.updatingIds.value.has(pendingReturn.id)).toBe(false)
  })

  it('does not resurrect a returned row when concurrent reloads resolve out of order', async () => {
    let resolveStaleReload!: (value: ReturnType<typeof pendingReturnsResponse>) => void
    const staleReload = new Promise<ReturnType<typeof pendingReturnsResponse>>(
      (resolve) => {
        resolveStaleReload = resolve
      },
    )
    axiosGet
      .mockResolvedValueOnce(
        pendingReturnsResponse([pendingReturn, secondPendingReturn]),
      )
      .mockReturnValueOnce(staleReload)
      .mockResolvedValueOnce(pendingReturnsResponse([]))
    axiosPut.mockResolvedValue({
      data: { success: true, data: { status: 'returned' } },
    })
    const state = usePendingReturns()
    await state.load()

    const firstUpdate = state.markReturned(pendingReturn.id)
    await vi.waitFor(() => expect(axiosGet).toHaveBeenCalledTimes(2))

    const secondUpdate = state.markReturned(secondPendingReturn.id)
    await vi.waitFor(() => expect(axiosGet).toHaveBeenCalledTimes(3))
    await secondUpdate

    resolveStaleReload(pendingReturnsResponse([secondPendingReturn]))
    await firstUpdate

    expect(state.rentals.value).toEqual([])
  })
})
