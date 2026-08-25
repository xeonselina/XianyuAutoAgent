import { flushPromises, mount } from '@vue/test-utils'
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  gantt: null as any,
  tenant: null as any,
}))

vi.mock('@/stores/gantt', async () => {
  const { reactive } = await vi.importActual<typeof import('vue')>('vue')
  mocks.gantt = reactive({
    devices: [] as any[],
    rentals: [] as any[],
    loading: false,
    loadData: vi.fn().mockResolvedValue(undefined),
    updateDeviceLifecycle: vi.fn().mockResolvedValue({ success: true }),
  })
  return {
    useGanttStore: () => mocks.gantt,
  }
})

vi.mock('@/stores/tenant', async () => {
  const { reactive } = await vi.importActual<typeof import('vue')>('vue')
  mocks.tenant = reactive({
    currentWarehouseId: 1 as number | 'all',
    initialize: vi.fn().mockResolvedValue([]),
    requireConcreteWarehouse: vi.fn(() => {
      if (mocks.tenant.currentWarehouseId === 'all') throw new Error('请选择具体仓库')
      return mocks.tenant.currentWarehouseId
    }),
  })
  return {
    useMobileTenantStore: () => mocks.tenant,
  }
})

vi.mock('vant', () => ({ showToast: vi.fn() }))

import DeviceStatusView from '../../../frontend-mobile/src/views/DeviceStatusView.vue'

const mountView = () => mount(DeviceStatusView, {
  global: {
    mocks: { $router: { back: vi.fn() } },
    stubs: {
      'van-nav-bar': true,
      'van-tabs': true,
      'van-tab': true,
      'van-empty': true,
      'van-tag': true,
      'van-loading': true,
      'van-action-sheet': true,
    },
  },
})

describe('mobile DeviceStatusView warehouse isolation', () => {
  beforeAll(async () => {
    await import('@/stores/tenant')
  })

  beforeEach(() => {
    vi.clearAllMocks()
    mocks.gantt.devices = []
    mocks.gantt.rentals = []
    mocks.gantt.loading = false
    mocks.tenant.currentWarehouseId = 1
    mocks.tenant.initialize.mockResolvedValue([])
    mocks.gantt.loadData.mockResolvedValue(undefined)
  })

  it('initializes warehouses before loading and reloads from an empty state on a switch', async () => {
    const wrapper = mountView()
    await flushPromises()
    expect(mocks.tenant.initialize).toHaveBeenCalledOnce()
    expect(mocks.gantt.loadData).toHaveBeenCalledOnce()

    mocks.gantt.devices = [{ id: 1, warehouse_id: 1 }]
    const setup = wrapper.vm.$.setupState as any
    setup.targetDevice = mocks.gantt.devices[0]
    setup.showLifecycleSheet = true
    mocks.tenant.currentWarehouseId = 2

    expect(mocks.gantt.devices).toEqual([])
    expect(setup.targetDevice).toBeNull()
    expect(setup.showLifecycleSheet).toBe(false)
    await flushPromises()
    expect(mocks.gantt.loadData).toHaveBeenCalledTimes(2)
  })

  it('does not open lifecycle controls or write from the all-warehouses view', async () => {
    const wrapper = mountView()
    await flushPromises()
    const setup = wrapper.vm.$.setupState as any
    const device = { id: 1, warehouse_id: 1 }
    mocks.tenant.currentWarehouseId = 'all'

    setup.openLifecyclePicker(device)
    expect(setup.showLifecycleSheet).toBe(false)
    setup.targetDevice = device
    await setup.onLifecycleSelect({ name: '已售出', value: 'sold' })

    expect(mocks.gantt.updateDeviceLifecycle).not.toHaveBeenCalled()
  })

  it('fails closed when a forced lifecycle action targets another warehouse', async () => {
    const wrapper = mountView()
    await flushPromises()
    const setup = wrapper.vm.$.setupState as any
    mocks.tenant.currentWarehouseId = 2
    setup.targetDevice = { id: 1, warehouse_id: 1 }

    await setup.onLifecycleSelect({ name: '已售出', value: 'sold' })

    expect(mocks.gantt.updateDeviceLifecycle).not.toHaveBeenCalled()
  })
})
