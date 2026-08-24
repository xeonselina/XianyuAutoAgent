import ElementPlus, { ElMessage } from 'element-plus'
import { flushPromises, shallowMount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import TenantIntegrationsView from '@/views/TenantIntegrationsView.vue'

const api = vi.hoisted(() => ({
  confirmTenantIntegrationCredentials: vi.fn(),
  createTenantIntegration: vi.fn(),
  listTenantIntegrations: vi.fn(),
  requestTenantIntegrationCredentialChallenge: vi.fn(),
}))

vi.mock('@/api/tenantIntegrations', () => api)

const integration = {
  integration_id: 'integration-1',
  provider: 'sf',
  name: '顺丰主连接',
  status: 'unconfigured',
  configured: false,
  last_verified_at: null,
  row_version: 1,
}

describe('TenantIntegrationsView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    sessionStorage.clear()
    localStorage.clear()
    vi.spyOn(globalThis.crypto, 'randomUUID')
      .mockReturnValue('11111111-1111-4111-8111-111111111111')
    vi.spyOn(ElMessage, 'success').mockImplementation(() => undefined as never)
    vi.spyOn(ElMessage, 'error').mockImplementation(() => undefined as never)
    vi.spyOn(ElMessage, 'warning').mockImplementation(() => undefined as never)
    api.listTenantIntegrations.mockResolvedValue([integration])
    api.requestTenantIntegrationCredentialChallenge.mockResolvedValue({
      intent_id: '11111111-1111-4111-8111-111111111111',
      challenge_id: 'challenge-1',
      expires_at: '2026-08-23T04:00:00Z',
      replayed: false,
    })
    api.confirmTenantIntegrationCredentials.mockResolvedValue({
      integration_id: integration.integration_id,
      revision_id: 'revision-1',
      revision_no: 1,
      status: 'pending_validation',
      verification_status: 'not_attempted',
      validation_event_id: 'event-1',
      idempotent: false,
    })
  })

  it('keeps credentials and action proof in component memory, then clears them', async () => {
    const wrapper = shallowMount(TenantIntegrationsView, {
      global: { plugins: [ElementPlus] },
    })
    await flushPromises()
    const state = wrapper.vm.$.setupState
    state.credentialValues = {
      partner_id: 'partner-id',
      checkword: 'secret-never-persisted',
    }

    await state.submitCredentials()
    expect(api.requestTenantIntegrationCredentialChallenge).toHaveBeenCalledWith(
      integration,
      '11111111-1111-4111-8111-111111111111',
      { partner_id: 'partner-id', checkword: 'secret-never-persisted' },
    )
    expect(state.challengeId).toBe('challenge-1')
    state.verificationCode = '123456'

    await state.submitCredentials()
    expect(api.confirmTenantIntegrationCredentials).toHaveBeenCalledWith(
      integration,
      {
        action_id: '11111111-1111-4111-8111-111111111111',
        challenge_id: 'challenge-1',
        code: '123456',
        credentials: {
          partner_id: 'partner-id',
          checkword: 'secret-never-persisted',
        },
      },
    )
    expect(state.credentialValues).toEqual({})
    expect(state.actionId).toBe('')
    expect(state.challengeId).toBe('')
    expect(state.verificationCode).toBe('')
    expect(sessionStorage.length).toBe(0)
    expect(localStorage.length).toBe(0)
    wrapper.unmount()
  })

  it('retains the action id after an ambiguous challenge failure for exact retry', async () => {
    api.requestTenantIntegrationCredentialChallenge
      .mockRejectedValueOnce(new Error('network unavailable'))
      .mockResolvedValueOnce({ challenge_id: 'challenge-1' })
    const wrapper = shallowMount(TenantIntegrationsView, {
      global: { plugins: [ElementPlus] },
    })
    await flushPromises()
    const state = wrapper.vm.$.setupState
    state.credentialValues = { partner_id: 'partner-id', checkword: 'secret' }

    await state.submitCredentials()
    expect(state.actionId).toBe('11111111-1111-4111-8111-111111111111')
    await state.submitCredentials()

    expect(api.requestTenantIntegrationCredentialChallenge).toHaveBeenCalledTimes(2)
    expect(api.requestTenantIntegrationCredentialChallenge.mock.calls[1][1])
      .toBe('11111111-1111-4111-8111-111111111111')
    wrapper.unmount()
  })
})
