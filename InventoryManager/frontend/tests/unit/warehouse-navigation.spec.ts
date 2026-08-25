import { createPinia, setActivePinia } from 'pinia'
import { flushPromises, mount, shallowMount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import AppHeader from '@/components/AppHeader.vue'
import RentalStatsView from '@/views/RentalStatsView.vue'
import SFTrackingView from '@/views/SFTrackingView.vue'
import { useAuthStore } from '@/stores/auth'
import { useGanttStore } from '@/stores/gantt'
import { useTenantStore } from '@/stores/tenant'
import {
  listWarehouseSettings,
  saveKuaimaiConfiguration,
  saveSfConfiguration,
} from '@/api/settings'
import { useMobileTenantStore } from '../../../frontend-mobile/src/stores/tenant'


const { axiosGet, axiosPut } = vi.hoisted(() => ({
  axiosGet: vi.fn(),
  axiosPut: vi.fn(),
}))

vi.mock('axios', () => ({
  default: {
    defaults: { headers: { common: {} } },
    get: axiosGet,
    post: vi.fn(),
    put: axiosPut,
  },
  isAxiosError: vi.fn(() => false),
}))

vi.mock('vue-router', () => ({
  RouterLink: {
    props: ['to'],
    template: '<a :href="to"><slot /></a>',
  },
  useRouter: () => ({ replace: vi.fn() }),
}))

const warehouses = [
  {
    id: 11,
    name: '深圳仓库',
    province: '广东省',
    city: '深圳市',
    sf_configured: true,
    kuaimai_configured: false,
    created_at: '2026-08-25T00:00:00Z',
    updated_at: '2026-08-25T00:00:00Z',
  },
  {
    id: 22,
    name: '杭州仓库',
    province: '浙江省',
    city: '杭州市',
    sf_configured: false,
    kuaimai_configured: true,
    created_at: '2026-08-25T00:00:00Z',
    updated_at: '2026-08-25T00:00:00Z',
  },
]

const deferred = <T>() => {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise
  })
  return { promise, resolve }
}

const mountHeader = async (role: 'admin' | 'operator') => {
  const pinia = createPinia()
  setActivePinia(pinia)
  const auth = useAuthStore()
  auth.applyTenantSession({
    csrf_token: 'csrf',
    member: {
      id: 7,
      phone: '+8613800138000',
      role,
      status: 'active',
    },
    tenant: {
      id: 3,
      name: '测试租户',
      status: 'active',
      provisioning_status: 'active',
      expires_at: '2026-09-30T00:00:00Z',
      access_status: 'active',
    },
  })
  const wrapper = mount(AppHeader, {
    global: {
      plugins: [pinia],
      stubs: {
        ElSelect: {
          props: ['modelValue'],
          emits: ['update:modelValue'],
          template: '<select data-testid="warehouse-selector" />',
        },
        ElOption: true,
      },
    },
  })
  await flushPromises()
  return { wrapper, tenant: useTenantStore() }
}

describe('warehouse-aware tenant navigation', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    axiosGet.mockReset()
    axiosPut.mockReset()
  })

  it('shares one warehouse initialization and marks the session ready only after it resolves', async () => {
    const response = deferred<{ data: { success: boolean; data: typeof warehouses } }>()
    axiosGet.mockReturnValue(response.promise)
    const tenant = useTenantStore()

    const first = tenant.initialize()
    const second = tenant.initialize()

    expect(tenant.ready).toBe(false)
    expect(axiosGet).toHaveBeenCalledOnce()

    response.resolve({ data: { success: true, data: warehouses } })
    await Promise.all([first, second])

    expect(tenant.ready).toBe(true)
    expect(tenant.currentWarehouseId).toBe(11)
  })

  it('ignores a late warehouse response after tenant state is reset', async () => {
    const response = deferred<{ data: { success: boolean; data: typeof warehouses } }>()
    axiosGet.mockReturnValue(response.promise)
    const tenant = useTenantStore()
    const pending = tenant.initialize()

    tenant.reset()
    response.resolve({ data: { success: true, data: warehouses } })
    await pending

    expect(tenant.ready).toBe(false)
    expect(tenant.warehouses).toEqual([])
    expect(tenant.currentWarehouseId).toBe('all')
  })

  it('auto-selects the sole warehouse without rendering another control', async () => {
    axiosGet.mockResolvedValue({
      data: { success: true, data: [warehouses[0]] },
    })

    const { wrapper, tenant } = await mountHeader('admin')

    expect(tenant.currentWarehouseId).toBe(11)
    expect(wrapper.find('[data-testid="warehouse-selector"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('深圳仓库')
  })

  it('defaults multiple warehouses to the first and allows an in-memory all selection', async () => {
    const setItem = vi.spyOn(Storage.prototype, 'setItem')
    axiosGet.mockResolvedValue({
      data: { success: true, data: warehouses },
    })

    const { wrapper, tenant } = await mountHeader('admin')
    expect(tenant.currentWarehouseId).toBe(11)
    expect(wrapper.find('[data-testid="warehouse-selector"]').exists()).toBe(true)

    tenant.selectWarehouse('all')

    expect(tenant.currentWarehouseId).toBe('all')
    expect(setItem).not.toHaveBeenCalled()
    setItem.mockRestore()
  })

  it('shows settings only to Admin while preserving the warehouse selector for Operator', async () => {
    axiosGet.mockResolvedValue({
      data: { success: true, data: warehouses },
    })

    const admin = await mountHeader('admin')
    expect(admin.wrapper.find('[data-testid="settings-link"]').exists()).toBe(true)
    admin.wrapper.unmount()

    const operator = await mountHeader('operator')
    expect(operator.wrapper.find('[data-testid="warehouse-selector"]').exists()).toBe(true)
    expect(operator.wrapper.find('[data-testid="settings-link"]').exists()).toBe(false)
  })

  it('uses configured flags without receiving secrets and leaves blank secret fields unchanged', async () => {
    axiosGet.mockResolvedValueOnce({
      data: {
        success: true,
        data: [{
          ...warehouses[0],
          sf_config: {
            warehouse_id: 11,
            partner_id: 'partner',
            checkword_configured: true,
            monthly_card_configured: true,
            test_mode: false,
            sender_name: '寄件人',
            sender_phone: '13800138000',
            sender_address: '科技园 1 号',
          },
          kuaimai_config: {
            warehouse_id: 11,
            app_id: 'app-id',
            app_secret_configured: true,
            printer_sn: 'printer-1',
          },
        }],
      },
    })
    axiosPut.mockResolvedValue({
      data: { success: true, data: {} },
    })

    const listed = await listWarehouseSettings()
    expect(listed[0].sf_config?.checkword_configured).toBe(true)
    expect(JSON.stringify(listed)).not.toContain('ciphertext')

    await saveSfConfiguration(11, {
      partner_id: 'partner',
      checkword: '',
      monthly_card: '',
      test_mode: false,
      sender_name: '寄件人',
      sender_phone: '13800138000',
      sender_address: '科技园 1 号',
    })
    await saveKuaimaiConfiguration(11, {
      app_id: 'app-id',
      app_secret: '',
      printer_sn: 'printer-1',
    })

    expect(axiosPut).toHaveBeenNthCalledWith(
      1,
      '/api/settings/warehouses/11/sf',
      expect.objectContaining({ checkword: '', monthly_card: '' }),
    )
    expect(axiosPut).toHaveBeenNthCalledWith(
      2,
      '/api/settings/warehouses/11/kuaimai',
      expect.objectContaining({ app_secret: '' }),
    )
  })

  it('sends the selected warehouse on business reads and requires a concrete warehouse for writes', async () => {
    const tenant = useTenantStore()
    tenant.setWarehousesForSession(warehouses)
    const gantt = useGanttStore()
    axiosGet.mockResolvedValue({
      data: { success: true, data: { devices: [], rentals: [] } },
    })
    const post = vi.mocked((await import('axios')).default.post)
    post.mockReset()

    tenant.selectWarehouse('all')
    await gantt.loadData()
    expect(axiosGet).toHaveBeenCalledWith('/api/gantt/data', {
      params: expect.objectContaining({ warehouse_id: 'all' }),
    })

    await expect(gantt.createRental({ device_id: 9 })).rejects.toThrow(
      '请选择具体仓库',
    )
    expect(post).not.toHaveBeenCalled()

    tenant.selectWarehouse(22)
    post.mockResolvedValue({ data: { success: true, data: {} } })
    await gantt.createRental({ device_id: 9 })

    expect(post).toHaveBeenCalledWith('/api/rentals', {
      device_id: 9,
      warehouse_id: 22,
    })
  })

  it('keeps the mobile warehouse selection in memory and blocks all for writes', () => {
    const mobile = useMobileTenantStore(createPinia() as never)
    mobile.setWarehousesForSession(warehouses)
    expect(mobile.currentWarehouseId).toBe(11)

    mobile.selectWarehouse('all')
    expect(() => mobile.requireConcreteWarehouse()).toThrow('请选择具体仓库')

    mobile.selectWarehouse(22)
    expect(mobile.requireConcreteWarehouse()).toBe(22)
  })

  it('loads rental statistics explicitly for the selected warehouse and refreshes after switching', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const tenant = useTenantStore()
    tenant.setWarehousesForSession(warehouses)
    const fetchMock = vi.fn().mockResolvedValue({
      json: vi.fn().mockResolvedValue({ success: false }),
    })
    vi.stubGlobal('fetch', fetchMock)

    const wrapper = shallowMount(RentalStatsView, {
      global: {
        plugins: [pinia],
        stubs: { ElTableColumn: true },
      },
    })
    await flushPromises()

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/rental-stats/models?warehouse_id=11',
    )
    expect(fetchMock.mock.calls.some(
      ([url]) => String(url).startsWith('/api/rental-stats/periodic?')
        && String(url).includes('warehouse_id=11'),
    )).toBe(true)
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/rental-stats/x200u-forecast?warehouse_id=11',
    )

    tenant.selectWarehouse(22)
    await flushPromises()

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/rental-stats/models?warehouse_id=22',
    )
    expect(fetchMock.mock.calls.some(
      ([url]) => String(url).startsWith('/api/rental-stats/periodic?')
        && String(url).includes('warehouse_id=22'),
    )).toBe(true)
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/rental-stats/x200u-forecast?warehouse_id=22',
    )

    wrapper.unmount()
    vi.unstubAllGlobals()
  })

  it('clears SF tracking rows synchronously and reloads after a warehouse switch', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const tenant = useTenantStore(); tenant.setWarehousesForSession(warehouses)
    axiosGet.mockResolvedValueOnce({ data: { success: true,
      data: [{ rental_id: 1, ship_out_tracking_no: 'SF-A' }] } })
    const wrapper = shallowMount(SFTrackingView, { global: { plugins: [pinia] } })
    await flushPromises()
    expect(axiosGet).toHaveBeenCalledWith('/api/sf-tracking/list', { params: expect.objectContaining({ warehouse_id: '11' }) })
    ;(wrapper.vm as any).trackingStatus = { 'SF-A': { status: 'picked_up' } }
    axiosGet.mockReturnValueOnce(new Promise(() => {}))

    tenant.selectWarehouse(22)

    expect((wrapper.vm as any).rentals).toEqual([])
    expect((wrapper.vm as any).trackingStatus).toEqual({})
    expect(axiosGet).toHaveBeenLastCalledWith('/api/sf-tracking/list', { params: expect.objectContaining({ warehouse_id: '22' }) })
    wrapper.unmount()
  })

  it.each([['viewTracking', { success: true, data: { status: 'stale' } }], ['batchRefresh', { success: false, message: 'stale failure' }]])('ignores stale %s POST completion after a warehouse switch', async (method, stale) => {
    const pinia = createPinia(); setActivePinia(pinia); const tenant = useTenantStore(); tenant.setWarehousesForSession(warehouses)
    axiosGet.mockResolvedValue({ data: { success: true, data: [{ rental_id: 1, ship_out_tracking_no: 'SF-A' }] } })
    const post = vi.mocked((await import('axios')).default.post); post.mockReset(); const old = deferred<any>(); post.mockReturnValueOnce(old.promise).mockReturnValueOnce(new Promise(() => {}))
    const alertSpy = vi.fn(); vi.stubGlobal('alert', alertSpy)
    const wrapper = shallowMount(SFTrackingView, { global: { plugins: [pinia] } }); await flushPromises(); const vm = wrapper.vm as any
    const invoke = () => method === 'viewTracking' ? vm.viewTracking('SF-A') : vm.batchRefresh()
    void invoke(); tenant.selectWarehouse(22); await flushPromises(); void invoke()
    old.resolve({ data: stale }); await flushPromises()
    expect(vm.trackingStatus).toEqual({}); expect(vm.currentTracking).toBeNull(); expect(alertSpy).not.toHaveBeenCalled()
    expect(method === 'viewTracking' ? vm.loadingTracking['SF-A'] : vm.loading).toBe(true)
    wrapper.unmount(); vi.unstubAllGlobals()
  })
})
