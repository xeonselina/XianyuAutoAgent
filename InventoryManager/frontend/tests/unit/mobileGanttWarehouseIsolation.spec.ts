import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  createPinia,
  setActivePinia,
} from '../../../frontend-mobile/node_modules/pinia/dist/pinia.mjs'
import axios from '../../../frontend-mobile/node_modules/axios/index.js'

const tenant = vi.hoisted(() => ({
  currentWarehouseId: 1 as number | 'all',
  initialize: vi.fn(),
  requireConcreteWarehouse: vi.fn(),
}))

vi.mock('@/stores/tenant', () => ({
  useMobileTenantStore: () => tenant,
}))

vi.mock('../../../frontend-mobile/node_modules/axios/index.js')

import { useGanttStore } from '../../../frontend-mobile/src/stores/gantt'

describe('mobile Gantt warehouse isolation', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    tenant.currentWarehouseId = 1
    tenant.initialize.mockResolvedValue([])
    tenant.requireConcreteWarehouse.mockImplementation(() => {
      if (tenant.currentWarehouseId === 'all') throw new Error('请选择具体仓库')
      return tenant.currentWarehouseId
    })
  })

  it('clears old rows before a new warehouse request and keeps them empty on failure', async () => {
    const store = useGanttStore()
    store.devices = [{ id: 1, warehouse_id: 1 } as any]
    store.rentals = [{ id: 11, warehouse_id: 1 } as any]
    vi.mocked(axios.get).mockRejectedValueOnce(new Error('B 仓加载失败'))
    tenant.currentWarehouseId = 2

    const loadB = store.loadData()

    expect(store.devices).toEqual([])
    expect(store.rentals).toEqual([])
    await loadB
    expect(store.devices).toEqual([])
    expect(store.rentals).toEqual([])
    expect(store.error).toBe('B 仓加载失败')
  })

  it('does not let an old rejection overwrite the current warehouse state', async () => {
    let rejectA!: (reason?: any) => void
    const requestA = new Promise((_resolve, reject) => { rejectA = reject })
    vi.mocked(axios.get)
      .mockReturnValueOnce(requestA as never)
      .mockResolvedValueOnce({
        data: {
          success: true,
          data: {
            devices: [{ id: 2, name: 'B 设备', warehouse_id: 2 }],
            rentals: [],
          },
        },
      })
    const store = useGanttStore()

    const loadA = store.loadData()
    await vi.waitFor(() => expect(axios.get).toHaveBeenCalledOnce())
    tenant.currentWarehouseId = 2
    await store.loadData()
    rejectA(new Error('A 仓旧请求失败'))
    await loadA

    expect(store.devices[0]?.name).toBe('B 设备')
    expect(store.error).toBeNull()
    expect(store.loading).toBe(false)
  })

  it('blocks direct writes for devices and rentals outside the selected warehouse', async () => {
    tenant.currentWarehouseId = 2
    const store = useGanttStore()
    store.devices = [{ id: 1, warehouse_id: 1 } as any]
    store.rentals = [{ id: 11, warehouse_id: 1 } as any]

    const actions = [
      () => store.updateRental(11, { end_date: '2026-09-01' }),
      () => store.deleteRental(11),
      () => store.shipRentalToXianyu(11),
      () => store.updateDeviceLifecycle(1, 'sold'),
    ]
    for (const action of actions) {
      await expect(action()).rejects.toThrow('记录不属于当前仓库')
    }

    expect(axios.put).not.toHaveBeenCalled()
    expect(axios.delete).not.toHaveBeenCalled()
    expect(axios.post).not.toHaveBeenCalled()
  })
})
