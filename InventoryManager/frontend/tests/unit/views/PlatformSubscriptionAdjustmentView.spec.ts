import ElementPlus, { ElMessage } from 'element-plus'
import { flushPromises, shallowMount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'

import PlatformSubscriptionAdjustmentView from '@/views/PlatformSubscriptionAdjustmentView.vue'


const api = vi.hoisted(() => ({
  commitPlatformSubscriptionAdjustment: vi.fn(),
  getPlatformTenant: vi.fn(),
  previewPlatformSubscriptionAdjustment: vi.fn(),
}))
const router = vi.hoisted(() => ({ push: vi.fn() }))

vi.mock('@/api/platformIdentity', () => api)
vi.mock('vue-router', () => ({
  useRoute: () => ({ params: { tenantId: 'tenant-1' } }),
  useRouter: () => router,
}))

const tenant = {
  tenant_id: 'tenant-1',
  name: '测试租户',
  status: 'active',
  subscription: {
    subscription_id: 'subscription-1',
    status: 'active',
    expires_at: '2026-09-01T00:00:00Z',
    row_version: 4,
  },
}

const preview = {
  action_id: 'action-1',
  confirmation_token: 'memory-only-confirmation',
  operation: 'add_days',
  days: 3,
  database_effective_at: '2026-08-22T12:00:00Z',
  calculation_base_at: '2026-09-01T00:00:00Z',
  before_expires_at: '2026-09-01T00:00:00Z',
  after_expires_at: '2026-09-04T00:00:00Z',
  before_status: 'active',
  after_status: 'active',
  expected_tenant_row_version: 3,
  expected_subscription_row_version: 4,
  expires_at: '2026-08-22T12:05:00Z',
}

describe('PlatformSubscriptionAdjustmentView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    sessionStorage.clear()
    localStorage.clear()
    vi.spyOn(globalThis.crypto, 'randomUUID')
      .mockReturnValue('11111111-1111-4111-8111-111111111111')
    api.getPlatformTenant.mockResolvedValue(tenant)
    api.previewPlatformSubscriptionAdjustment.mockResolvedValue(preview)
    api.commitPlatformSubscriptionAdjustment.mockResolvedValue({
      tenant_id: 'tenant-1',
      subscription_id: 'subscription-1',
      event_id: 'event-1',
      action_id: 'action-1',
      operation: 'add_days',
      signed_delta_days: 3,
      database_effective_at: '2026-08-22T12:00:01Z',
      calculation_base_at: '2026-09-01T00:00:00Z',
      before_expires_at: '2026-09-01T00:00:00Z',
      after_expires_at: '2026-09-04T00:00:00Z',
      before_status: 'active',
      after_status: 'active',
      resulting_subscription_row_version: 5,
      created: true,
      refund_disclaimer: 'This record does not prove a refund.',
    })
    vi.spyOn(ElMessage, 'success').mockImplementation(() => undefined as never)
    vi.spyOn(ElMessage, 'error').mockImplementation(() => undefined as never)
    vi.spyOn(ElMessage, 'warning').mockImplementation(() => undefined as never)
  })

  afterEach(() => vi.restoreAllMocks())

  const mountView = () => shallowMount(PlatformSubscriptionAdjustmentView, {
    global: { plugins: [ElementPlus] },
  })

  it('previews and commits only the three-action contract with a fresh factor', async () => {
    const wrapper = mountView()
    await flushPromises()
    const state = wrapper.vm.$.setupState
    state.days = 3
    state.note = 'Restore three service days.'

    await state.loadPreview()
    expect(api.previewPlatformSubscriptionAdjustment).toHaveBeenCalledWith(
      'tenant-1',
      {
        operation: 'add_days',
        days: 3,
        reason_code: 'customer_compensation',
        note: 'Restore three service days.',
        offline_reference: null,
        idempotency_key: 'd53:11111111-1111-4111-8111-111111111111',
      },
    )
    state.factorMethod = 'recovery_code'
    await nextTick()
    state.factor = 'single-use-recovery'

    await state.submitAdjustment()

    expect(api.commitPlatformSubscriptionAdjustment).toHaveBeenCalledWith(
      'tenant-1',
      expect.objectContaining({
        action_id: 'action-1',
        confirmation_token: 'memory-only-confirmation',
        expected_subscription_row_version: 4,
        factor_method: 'recovery_code',
        factor: 'single-use-recovery',
      }),
    )
    const committed = api.commitPlatformSubscriptionAdjustment.mock.calls[0][1]
    expect(committed).not.toHaveProperty('target_expires_at')
    expect(state.preview).toBeNull()
    expect(state.factor).toBe('')
    expect(api.getPlatformTenant).toHaveBeenCalledTimes(2)
    expect(sessionStorage.length).toBe(0)
    expect(localStorage.length).toBe(0)
    wrapper.unmount()
  })

  it('invalidates confirmation on form change and clears it on unmount', async () => {
    const wrapper = mountView()
    await flushPromises()
    const state = wrapper.vm.$.setupState
    await state.loadPreview()
    expect(state.preview.confirmation_token).toBe('memory-only-confirmation')

    state.reasonCode = 'manual_correction'
    await nextTick()
    expect(state.preview).toBeNull()

    await state.loadPreview()
    state.factor = 'not-persisted'
    wrapper.unmount()
    expect(state.preview).toBeNull()
    expect(state.factor).toBe('')
    expect(sessionStorage.length).toBe(0)
    expect(localStorage.length).toBe(0)
  })
})
