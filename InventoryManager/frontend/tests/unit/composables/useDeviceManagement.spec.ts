import axios from 'axios'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useDeviceManagement } from '@/composables/useDeviceManagement'
import { useGanttStore } from '@/stores/gantt'
import { useTenantStore } from '@/stores/tenant'

vi.mock('axios', () => ({ default: { get: vi.fn() } }))

const device = { id: 7, name: '设备七', is_accessory: false, warehouse_id: 1 }
const deferred = <T>() => {
  let resolve!: (value: T) => void
  const promise = new Promise<T>(done => { resolve = done })
  return { promise, resolve }
}

const setWarehouse = (id: number) => useTenantStore().setWarehousesForSession([
  { id, name: `仓库${id}`, province: '广东', city: '深圳' },
])

describe('useDeviceManagement independent booking options', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    setActivePinia(createPinia())
    setWarehouse(1)
  })

  it('loads all device pages when the Gantt store is empty', async () => {
    const store = useGanttStore()
    expect(store.devices).toEqual([])
    vi.mocked(axios.get)
      .mockResolvedValueOnce({ data: { devices: [device], has_next: true } })
      .mockResolvedValueOnce({ data: { devices: [{ ...device, id: 8, name: '设备八' }], has_next: false } })
    const management = useDeviceManagement()
    await management.loadDevices()
    expect(management.devices.value.map(row => row.name)).toEqual(['设备七', '设备八'])
    expect(axios.get).toHaveBeenNthCalledWith(2, '/api/devices', {
      params: { is_accessory: false, page: 2, per_page: 100, warehouse_id: 1 },
    })
    expect(store.devices).toEqual([])
  })

  it('ignores an older warehouse request that completes after the new request', async () => {
    const old = deferred<any>()
    vi.mocked(axios.get).mockReturnValueOnce(old.promise)
    const management = useDeviceManagement()
    const first = management.loadDevices()
    await vi.waitFor(() => expect(axios.get).toHaveBeenCalledTimes(1))
    setWarehouse(2)
    vi.mocked(axios.get).mockResolvedValueOnce({ data: { devices: [{ ...device, id: 9, warehouse_id: 2 }], has_next: false } })
    await management.loadDevices()
    old.resolve({ data: { devices: [device], has_next: true } })
    await first
    expect(management.devices.value.map(row => row.id)).toEqual([9])
    expect(axios.get).toHaveBeenCalledTimes(2)
  })
})
