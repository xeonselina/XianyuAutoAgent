import ElementPlus, { ElMessage } from 'element-plus'
import { flushPromises, shallowMount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import InvitationAcceptanceView from '@/views/InvitationAcceptanceView.vue'


const api = vi.hoisted(() => ({
  inspectTenantInvitation: vi.fn(),
  requestTenantInvitationCode: vi.fn(),
  acceptTenantInvitation: vi.fn(),
}))

vi.mock('@/api/tenantIdentity', () => api)

describe('InvitationAcceptanceView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    window.history.replaceState(
      null,
      '',
      '/invite#invitation=invite-1&generation=2&token=one-time-secret',
    )
    api.inspectTenantInvitation.mockResolvedValue({
      invitation_id: 'invite-1',
      tenant_name: '演示租户',
      role: 'operator',
      masked_phone: '+8613****8002',
      expires_at: '2026-08-30T00:00:00Z',
    })
    api.requestTenantInvitationCode.mockResolvedValue({
      challenge_id: 'challenge-1',
      expires_in_seconds: 300,
      resend_after_seconds: 60,
    })
    api.acceptTenantInvitation.mockResolvedValue({ accepted: true })
    vi.spyOn(ElMessage, 'success').mockImplementation(() => undefined as never)
    vi.spyOn(ElMessage, 'error').mockImplementation(() => undefined as never)
  })

  afterEach(() => vi.restoreAllMocks())

  it('consumes the fragment before inspection and keeps OTP handoff in memory', async () => {
    const wrapper = shallowMount(InvitationAcceptanceView, {
      global: {
        plugins: [ElementPlus],
        directives: { loading: () => undefined },
        mocks: { $router: { replace: vi.fn() } },
      },
    })
    await flushPromises()
    const state = wrapper.vm.$.setupState

    expect(window.location.hash).toBe('')
    expect(api.inspectTenantInvitation).toHaveBeenCalledWith({
      invitation_id: 'invite-1',
      token: 'one-time-secret',
      generation: 2,
    })
    await state.requestCode()
    state.code = '123456'
    await state.accept()

    expect(api.acceptTenantInvitation).toHaveBeenCalledWith(
      expect.objectContaining({ token: 'one-time-secret' }),
      'challenge-1',
      '123456',
    )
    expect(state.credential).toBeNull()
    expect(state.accepted).toBe(true)
  })
})
