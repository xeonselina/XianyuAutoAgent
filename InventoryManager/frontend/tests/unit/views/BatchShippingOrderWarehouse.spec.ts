import ElementPlus from 'element-plus'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { nextTick } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import axios from 'axios'

import BatchShippingOrderView from '@/views/BatchShippingOrderView.vue'
import { useTenantStore } from '@/stores/tenant'

vi.mock('axios')
vi.mock('jsbarcode', () => ({ default: vi.fn() }))
vi.mock('vue-router', () => ({
  useRoute: () => ({
    query: { start_date: '2026-08-25', end_date: '2026-08-26' },
  }),
  useRouter: () => ({ push: vi.fn() }),
}))

const response = (rentals: any[]) => ({
  data: { success: true, data: { rentals } },
})

const mountView = () => {
  const pinia = createPinia()
  setActivePinia(pinia)
  useTenantStore().setWarehousesForSession([
    { id: 1, name: 'A 仓', province: '广东省', city: '深圳市' },
    { id: 2, name: 'B 仓', province: '浙江省', city: '杭州市' },
  ])
  return mount(BatchShippingOrderView, {
    global: {
      plugins: [pinia, ElementPlus],
      stubs: { teleport: true, transition: false },
    },
  })
}

describe('BatchShippingOrderView warehouse isolation', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('clears A orders as soon as the B request starts and stays empty if B fails', async () => {
    let rejectB!: (reason?: any) => void
    vi.mocked(axios.get)
      .mockResolvedValueOnce(response([{ id: 1, warehouse_id: 1, status: 'not_shipped' }]))
      .mockReturnValueOnce(
        new Promise((_resolve, reject) => { rejectB = reject }) as never,
      )
    const wrapper = mountView()
    await flushPromises()
    const setup = wrapper.vm.$.setupState as any
    expect(setup.rentals).toHaveLength(1)

    useTenantStore().selectWarehouse(2)
    await nextTick()
    expect(setup.rentals).toEqual([])
    rejectB(new Error('B 仓加载失败'))
    await vi.waitFor(() => expect(setup.loading).toBe(false))
    expect(setup.rentals).toEqual([])
  })

  it('does not print injected orders from another warehouse', async () => {
    vi.mocked(axios.get).mockResolvedValueOnce(response([]))
    const print = vi.fn()
    Object.defineProperty(window, 'print', { configurable: true, value: print })
    const wrapper = mountView()
    await flushPromises()
    const tenant = useTenantStore()
    tenant.selectWarehouse(2)
    const setup = wrapper.vm.$.setupState as any
    setup.rentals = [{ id: 1, warehouse_id: 1, status: 'not_shipped' }]

    setup.handlePrint()

    expect(print).not.toHaveBeenCalled()
  })
})
