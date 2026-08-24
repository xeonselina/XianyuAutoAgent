import ElementPlus, { ElMessage } from 'element-plus'
import { flushPromises, shallowMount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import TenantStatusView from '@/views/TenantStatusView.vue'


const api = vi.hoisted(() => ({
  clearTenantCsrfToken: vi.fn(),
  getTenantSessionStatus: vi.fn(),
  logoutCurrentSession: vi.fn(),
}))
const subscriptionApi = vi.hoisted(() => ({
  getTenantSubscriptionStatus: vi.fn(),
  redeemTenantSubscription: vi.fn(),
}))
const router = vi.hoisted(() => ({ push: vi.fn(), replace: vi.fn() }))

vi.mock('@/api/tenantIdentity', () => api)
vi.mock('@/api/tenantSubscription', () => subscriptionApi)
vi.mock('vue-router', () => ({ useRouter: () => router }))

describe('TenantStatusView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.getTenantSessionStatus.mockResolvedValue({
      effective_gate: 'suspended',
      role: 'admin',
    })
    api.logoutCurrentSession.mockResolvedValue({ logged_out: true })
    subscriptionApi.getTenantSubscriptionStatus.mockResolvedValue({
      effective_status: 'expired',
      expires_at: '2026-08-21T12:00:00Z',
      subscription_row_version: 4,
      can_redeem: true,
    })
    subscriptionApi.redeemTenantSubscription.mockResolvedValue({
      effective_status: 'active',
      expires_at: '2026-09-21T12:00:00Z',
      subscription_row_version: 5,
      idempotent_replay: false,
    })
    vi.spyOn(ElMessage, 'error').mockImplementation(() => undefined as never)
  })

  afterEach(() => vi.restoreAllMocks())

  it('allows only a suspended Admin to open account security', async () => {
    const wrapper = shallowMount(TenantStatusView, {
      global: {
        plugins: [ElementPlus],
        directives: { loading: () => undefined },
      },
    })
    await flushPromises()

    expect(wrapper.vm.$.setupState.canOpenSecurity).toBe(true)
  })

  it('logs out through the server before clearing tab CSRF state', async () => {
    const wrapper = shallowMount(TenantStatusView, {
      global: {
        plugins: [ElementPlus],
        directives: { loading: () => undefined },
      },
    })
    await flushPromises()

    await wrapper.vm.$.setupState.logout()

    expect(api.logoutCurrentSession).toHaveBeenCalledOnce()
    expect(api.clearTenantCsrfToken).toHaveBeenCalledOnce()
    expect(router.replace).toHaveBeenCalledWith({ name: 'tenant-login' })
  })

  it('lets an expired Admin redeem then rereads authority before navigation', async () => {
    api.getTenantSessionStatus
      .mockResolvedValueOnce({
        effective_gate: 'expired',
        role: 'admin',
      })
      .mockResolvedValueOnce({
        effective_gate: 'active',
        role: 'admin',
      })
    vi.spyOn(globalThis.crypto, 'randomUUID')
      .mockReturnValue('10000000-0000-4000-8000-000000000001')
    const wrapper = shallowMount(TenantStatusView, {
      global: {
        plugins: [ElementPlus],
        directives: { loading: () => undefined },
      },
    })
    await flushPromises()
    wrapper.vm.$.setupState.redemptionCode = 'CODE-VALUE'

    await wrapper.vm.$.setupState.redeem()

    expect(subscriptionApi.redeemTenantSubscription).toHaveBeenCalledWith({
      code: 'CODE-VALUE',
      idempotency_key: (
        'subscription-renewal:10000000-0000-4000-8000-000000000001'
      ),
      expected_subscription_row_version: 4,
    })
    expect(api.getTenantSessionStatus).toHaveBeenCalledTimes(2)
    expect(router.replace).toHaveBeenCalledWith({ name: 'gantt' })
  })
})
