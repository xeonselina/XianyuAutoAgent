import ElementPlus, { ElMessage } from 'element-plus'
import { flushPromises, shallowMount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import PlatformTenantsView from '@/views/PlatformTenantsView.vue'


const api = vi.hoisted(() => ({
  getPlatformTenant: vi.fn(),
  getPlatformTenantRentalCustomerPii: vi.fn(),
  listPlatformTenantDevices: vi.fn(),
  listPlatformTenantRentals: vi.fn(),
  listPlatformTenantWarehouses: vi.fn(),
  listPlatformTenants: vi.fn(),
}))
const router = vi.hoisted(() => ({ push: vi.fn() }))

vi.mock('@/api/platformIdentity', () => api)
vi.mock('vue-router', () => ({ useRouter: () => router }))

const item = {
  tenant_id: '31000000-0000-4000-8000-000000000001',
  name: '甲租户',
  slug: 'tenant-a',
  status: 'active',
  timezone: 'Asia/Shanghai',
  tenant_row_version: 3,
  subscription_status: 'active',
  subscription_expires_at: '2026-08-30T00:00:00Z',
  subscription_row_version: 2,
  database_status: 'ready',
  updated_at: '2026-08-22T00:00:00Z',
}

describe('PlatformTenantsView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.listPlatformTenants.mockResolvedValue({
      items: [item],
      page: 1,
      page_size: 25,
      has_more: false,
      status_filter: null,
    })
    api.getPlatformTenant.mockResolvedValue({
      ...item,
      access_version: 9,
      locale: 'zh-CN',
      created_at: item.updated_at,
      public_identity_published_at: item.updated_at,
      subscription: null,
      database_route: null,
    })
    api.listPlatformTenantRentals.mockResolvedValue({
      items: [{
        rental_id: 7,
        device: { device_id: 3, name: '设备 A', model: 'x200u' },
        start_date: '2026-08-25',
        end_date: '2026-08-27',
        status: 'shipped',
        customer: {
          name_masked: '张**',
          phone_masked: '*******8000',
          region_masked: '已设置',
        },
        order_amount: '100.00',
        actual_shipped_at: null,
        actual_returned_at: null,
        created_at: '2026-08-22T00:00:00Z',
        updated_at: '2026-08-22T00:00:00Z',
      }],
      page: 1,
      page_size: 25,
      has_more: false,
      status_filter: null,
    })
    api.listPlatformTenantDevices.mockResolvedValue({
      items: [{
        device_id: 3,
        name: '设备 A',
        model: 'x200u',
        model_id: null,
        is_accessory: false,
        warehouse_id: 2,
        lifecycle_status: 'active',
        lifecycle_date: null,
        created_at: item.updated_at,
        updated_at: item.updated_at,
      }],
      page: 1,
      page_size: 100,
      has_more: false,
      lifecycle_status_filter: null,
    })
    api.listPlatformTenantWarehouses.mockResolvedValue({
      items: [{
        warehouse_id: 2,
        warehouse_uuid: '32000000-0000-4000-8000-000000000002',
        name: '默认仓',
        status: 'active',
        setup_state: 'ready',
        is_default: true,
        created_at: item.updated_at,
        updated_at: item.updated_at,
      }],
      page: 1,
      page_size: 100,
      has_more: false,
      status_filter: null,
      setup_state_filter: null,
    })
    api.getPlatformTenantRentalCustomerPii.mockResolvedValue({
      rental_id: 7,
      customer: {
        name: '张三',
        phone: '13800138000',
        address: {
          province: '广东省',
          city: '深圳市',
          district: '南山区',
          detail: '科技园 1 号',
        },
      },
    })
    vi.spyOn(ElMessage, 'error').mockImplementation(() => undefined as never)
  })

  afterEach(() => vi.restoreAllMocks())

  it('loads only the minimized directory page and opens one exact detail', async () => {
    const wrapper = shallowMount(PlatformTenantsView, {
      global: {
        plugins: [ElementPlus],
        directives: { loading: () => undefined },
      },
    })
    await flushPromises()
    const state = wrapper.vm.$.setupState

    expect(api.listPlatformTenants).toHaveBeenCalledWith({
      page: 1,
      page_size: 25,
      status: undefined,
    })
    expect(state.items).toEqual([item])
    expect(wrapper.text()).not.toContain('settings_json')
    expect(wrapper.text()).not.toContain('database_name')

    await state.openDetail(item.tenant_id)
    expect(api.getPlatformTenant).toHaveBeenCalledWith(
      item.tenant_id,
      expect.any(AbortSignal),
    )
    expect(state.detail.tenant_id).toBe(item.tenant_id)
    expect(api.listPlatformTenantRentals).toHaveBeenCalledWith(
      item.tenant_id,
      { page: 1, page_size: 25, status: undefined },
      expect.any(AbortSignal),
    )
    expect(state.rentals[0].customer).toEqual({
      name_masked: '张**',
      phone_masked: '*******8000',
      region_masked: '已设置',
    })
    expect(api.listPlatformTenantDevices).toHaveBeenCalledWith(
      item.tenant_id,
      { page: 1, page_size: 100 },
      expect.any(AbortSignal),
    )
    expect(api.listPlatformTenantWarehouses).toHaveBeenCalledWith(
      item.tenant_id,
      { page: 1, page_size: 100 },
      expect.any(AbortSignal),
    )
    expect(state.devices[0].name).toBe('设备 A')
    expect(state.warehouses[0].name).toBe('默认仓')
    wrapper.unmount()
  })

  it('resets pagination when the status filter changes', async () => {
    const wrapper = shallowMount(PlatformTenantsView, {
      global: {
        plugins: [ElementPlus],
        directives: { loading: () => undefined },
      },
    })
    await flushPromises()
    const state = wrapper.vm.$.setupState
    state.page = 3
    state.status = 'suspended'

    await state.resetAndLoad()

    expect(state.page).toBe(1)
    expect(api.listPlatformTenants).toHaveBeenLastCalledWith({
      page: 1,
      page_size: 25,
      status: 'suspended',
    })
    wrapper.unmount()
  })

  it('clears tenant A data immediately and ignores its late responses after switching', async () => {
    let resolveA: ((value: unknown) => void) | undefined
    const tenantA = { ...item, tenant_id: '31000000-0000-4000-8000-00000000000a' }
    const tenantB = { ...item, tenant_id: '31000000-0000-4000-8000-00000000000b' }
    api.getPlatformTenant
      .mockImplementationOnce(() => new Promise((resolve) => { resolveA = resolve }))
      .mockResolvedValueOnce({
        ...tenantB,
        access_version: 2,
        locale: 'zh-CN',
        created_at: tenantB.updated_at,
        public_identity_published_at: tenantB.updated_at,
        subscription: null,
        database_route: null,
      })
    const wrapper = shallowMount(PlatformTenantsView, {
      global: {
        plugins: [ElementPlus],
        directives: { loading: () => undefined },
      },
    })
    await flushPromises()
    const state = wrapper.vm.$.setupState

    const pendingA = state.openDetail(tenantA.tenant_id)
    await Promise.resolve()
    const pendingB = state.openDetail(tenantB.tenant_id)
    expect(state.detail).toBeNull()
    expect(state.rentals).toEqual([])
    await pendingB
    resolveA?.({
      ...tenantA,
      access_version: 1,
      locale: 'zh-CN',
      created_at: tenantA.updated_at,
      public_identity_published_at: tenantA.updated_at,
      subscription: null,
      database_route: null,
    })
    await pendingA

    expect(state.detail.tenant_id).toBe(tenantB.tenant_id)
    expect(api.listPlatformTenantRentals).toHaveBeenCalledTimes(1)
    expect(api.listPlatformTenantRentals).toHaveBeenCalledWith(
      tenantB.tenant_id,
      expect.anything(),
      expect.any(AbortSignal),
    )
    wrapper.unmount()
  })

  it('reads one PII resource with a reason and clears it on tenant switch', async () => {
    const wrapper = shallowMount(PlatformTenantsView, {
      global: {
        plugins: [ElementPlus],
        directives: { loading: () => undefined },
      },
    })
    await flushPromises()
    const state = wrapper.vm.$.setupState
    await state.openDetail(item.tenant_id)
    state.openPiiDialog(7)
    state.piiReason = 'support_case'

    await state.loadCustomerPii()

    expect(api.getPlatformTenantRentalCustomerPii).toHaveBeenCalledWith(
      item.tenant_id,
      7,
      'support_case',
      expect.any(AbortSignal),
    )
    expect(state.piiDetail.customer.phone).toBe('13800138000')

    await state.openDetail('31000000-0000-4000-8000-00000000000b')

    expect(state.piiDetail).toBeNull()
    expect(state.piiReason).toBe('')
    expect(state.selectedPiiRentalId).toBeNull()
    wrapper.unmount()
  })
})
