import ElementPlus from 'element-plus'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { nextTick } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import axios from 'axios'

import BatchShippingOrderView from '@/views/BatchShippingOrderView.vue'
import singleViewSource from '@/views/ShippingOrderView.vue?raw'
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
    {
      id: 1, name: 'A 仓', province: '广东省', city: '深圳市',
      return_contact: { name: 'A 联系人', phone: '13800138000', detail: '广东省深圳市南山区科技园' },
    },
    { id: 2, name: 'B 仓', province: '浙江省', city: '杭州市', return_contact: { name: 'B 联系人', phone: '13900139000', detail: '滨江区科技园' } },
    { id: 3, name: 'C 仓', province: '江苏省', city: '南京市', return_contact: { name: '', phone: '', detail: '' } },
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
    vi.mocked(axios.get).mockResolvedValue(response([]))
    const print = vi.fn()
    Object.defineProperty(window, 'print', { configurable: true, value: print })
    const wrapper = mountView()
    await flushPromises()
    const tenant = useTenantStore()
    tenant.selectWarehouse(2)
    await flushPromises()
    const setup = wrapper.vm.$.setupState as any
    setup.rentals = [{ id: 1, warehouse_id: 1, status: 'not_shipped' }]

    setup.handlePrint()

    expect(print).not.toHaveBeenCalled()
  })

  it('shows incomplete warehouse contact and refuses to print', async () => {
    vi.mocked(axios.get).mockResolvedValue(response([]))
    const print = vi.fn()
    Object.defineProperty(window, 'print', { configurable: true, value: print })
    const wrapper = mountView()
    await flushPromises()
    useTenantStore().selectWarehouse(3)
    await flushPromises()
    const setup = wrapper.vm.$.setupState as any
    setup.rentals = [{ id: 1, warehouse_id: 3, status: 'not_shipped' }]
    await nextTick()

    setup.handlePrint()

    expect(wrapper.text()).toContain('仓库寄回信息未配置')
    expect(print).not.toHaveBeenCalled()
  })

  it('renders and prints with the selected warehouse return contact', async () => {
    vi.mocked(axios.get).mockResolvedValueOnce(response([{
      id: 1, warehouse_id: 1, status: 'not_shipped',
    }]))
    const print = vi.fn()
    Object.defineProperty(window, 'print', { configurable: true, value: print })
    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain('广东省深圳市南山区科技园')
    expect(wrapper.text()).not.toContain('广东省深圳市广东省深圳市')
    expect(wrapper.text()).toContain('仓库联系人：A 联系人，13800138000')
    ;(wrapper.vm.$.setupState as any).handlePrint()
    expect(print).toHaveBeenCalledOnce()
  })

  it('keeps the single shipping sheet bound to its rental warehouse contact', () => {
    const guard = singleViewSource.indexOf('if (!returnContact.value)')
    expect(singleViewSource).toContain('await tenantStore.initialize()')
    expect(singleViewSource).toContain('warehouse.id === rental.value?.warehouse_id')
    expect(singleViewSource).toContain('v-if="returnContact"')
    expect(singleViewSource).toContain('v-else>仓库寄回信息未配置')
    expect(guard).toBeGreaterThan(-1)
    expect(singleViewSource.indexOf('window.print()')).toBeGreaterThan(guard)
    expect(singleViewSource).not.toMatch(/***REMOVED***|vacuumdust|张女士|松坪村***REMOVED***4单元415|小二微信/)
  })
})
