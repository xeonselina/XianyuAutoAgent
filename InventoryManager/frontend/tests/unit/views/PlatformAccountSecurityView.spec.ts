import ElementPlus, { ElMessage, ElMessageBox } from 'element-plus'
import { flushPromises, shallowMount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import PlatformAccountSecurityView from '@/views/PlatformAccountSecurityView.vue'


const api = vi.hoisted(() => ({
  beginPlatformTotpReplacement: vi.fn(),
  clearPlatformCsrfToken: vi.fn(),
  completePlatformTotpReplacement: vi.fn(),
  getPlatformSessionStatus: vi.fn(),
  listPlatformSessions: vi.fn(),
  logoutPlatformSession: vi.fn(),
  revokeAllPlatformSessions: vi.fn(),
  revokePlatformSession: vi.fn(),
  regeneratePlatformRecoveryCodes: vi.fn(),
  stepUpPlatformSession: vi.fn(),
}))
const router = vi.hoisted(() => ({ replace: vi.fn() }))

vi.mock('@/api/platformIdentity', () => api)
vi.mock('vue-router', () => ({ useRouter: () => router }))

const current = {
  session_id: '11111111-1111-4111-8111-111111111111',
  device_name: '当前浏览器',
  mfa_method: 'totp',
  created_at: '2026-08-22T08:00:00Z',
  last_seen_at: '2026-08-22T09:00:00Z',
  idle_expires_at: '2026-08-22T10:00:00Z',
  absolute_expires_at: '2026-08-23T08:00:00Z',
  current: true,
}
const other = {
  ...current,
  session_id: '22222222-2222-4222-8222-222222222222',
  device_name: '办公室浏览器',
  current: false,
}

describe('PlatformAccountSecurityView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.getPlatformSessionStatus.mockResolvedValue({
      session_id: current.session_id,
      platform_admin_id: 'admin-1',
      username: 'root.admin',
      role: 'platform_admin',
      mfa_method: 'totp',
    })
    api.listPlatformSessions.mockResolvedValue([current, other])
    api.revokePlatformSession.mockResolvedValue({
      revoked: true,
      current_session_revoked: false,
    })
    api.stepUpPlatformSession.mockResolvedValue({
      csrf_token: 'rotated-csrf',
      session_id: 'replacement-session',
      role: 'platform_admin',
      mfa_method: 'totp',
      mfa_verified_at: '2026-08-22T09:30:00Z',
    })
    api.regeneratePlatformRecoveryCodes.mockResolvedValue({
      recovery_code_generation: 2,
      recovery_codes: ['new-recovery-1', 'new-recovery-2'],
    })
    api.beginPlatformTotpReplacement.mockResolvedValue({
      credential_id: 'credential-2',
      base32_seed: 'NEWBASE32SEED',
    })
    api.completePlatformTotpReplacement.mockResolvedValue({
      totp_generation: 2,
      recovery_code_generation: 3,
      recovery_codes: ['final-recovery-1'],
      revoked_session_count: 2,
    })
    vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue('confirm')
    vi.spyOn(ElMessage, 'success').mockImplementation(() => undefined as never)
    vi.spyOn(ElMessage, 'error').mockImplementation(() => undefined as never)
  })

  afterEach(() => vi.restoreAllMocks())

  it('loads fixed platform session projections and revokes another device', async () => {
    const wrapper = shallowMount(PlatformAccountSecurityView, {
      global: {
        plugins: [ElementPlus],
        directives: { loading: () => undefined },
      },
    })
    await flushPromises()
    const state = wrapper.vm.$.setupState

    expect(state.sessions).toEqual([current, other])
    expect(wrapper.text()).not.toContain('token_digest')

    await state.revokeOne(other)
    expect(api.revokePlatformSession).toHaveBeenCalledWith(other.session_id)
    expect(state.sessions).toEqual([current])
    expect(api.clearPlatformCsrfToken).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('submits a fresh factor, clears it, and reloads after session rotation', async () => {
    const wrapper = shallowMount(PlatformAccountSecurityView, {
      global: {
        plugins: [ElementPlus],
        directives: { loading: () => undefined },
      },
    })
    await flushPromises()
    const state = wrapper.vm.$.setupState
    state.stepUpFactor = '123456'

    await state.refreshRecentMfa()

    expect(api.stepUpPlatformSession).toHaveBeenCalledWith({
      factor_method: 'totp',
      factor: '123456',
    })
    expect(state.stepUpFactor).toBe('')
    expect(api.getPlatformSessionStatus).toHaveBeenCalledTimes(2)
    expect(api.listPlatformSessions).toHaveBeenCalledTimes(2)
    wrapper.unmount()
  })

  it('keeps replacement secrets in component memory and empties sessions after atomic rotation', async () => {
    const wrapper = shallowMount(PlatformAccountSecurityView, {
      global: {
        plugins: [ElementPlus],
        directives: { loading: () => undefined },
      },
    })
    await flushPromises()
    const state = wrapper.vm.$.setupState
    state.factorMethod = 'recovery_code'
    state.factorValue = 'old-recovery'

    await state.regenerateRecoveryCodes()
    expect(api.regeneratePlatformRecoveryCodes).toHaveBeenCalledWith({
      factor_method: 'recovery_code', factor: 'old-recovery',
    })
    expect(state.displayedRecoveryCodes).toEqual([
      'new-recovery-1', 'new-recovery-2',
    ])
    expect(state.factorValue).toBe('')

    state.factorValue = 'new-recovery-1'
    await state.beginTotpReplacement()
    expect(state.pendingTotp).toEqual({
      credential_id: 'credential-2', base32_seed: 'NEWBASE32SEED',
    })
    state.replacementTotpCode = '123456'
    await state.completeTotpReplacement()
    expect(api.completePlatformTotpReplacement).toHaveBeenCalledWith(
      'credential-2', '123456',
    )
    expect(state.factorSessionRevoked).toBe(true)
    expect(state.sessions).toEqual([])
    expect(state.displayedRecoveryCodes).toEqual(['final-recovery-1'])

    wrapper.unmount()
    expect(state.displayedRecoveryCodes).toEqual([])
    expect(state.pendingTotp).toBeNull()
  })
})
