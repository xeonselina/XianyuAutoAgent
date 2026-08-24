import ElementPlus, { ElMessage } from 'element-plus'
import { shallowMount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import PlatformSetupView from '@/views/PlatformSetupView.vue'


const api = vi.hoisted(() => ({
  beginPlatformTotpSetup: vi.fn(),
  completePlatformSetup: vi.fn(),
  consumePlatformSetupToken: vi.fn(),
  setPlatformSetupPassword: vi.fn(),
}))
const router = vi.hoisted(() => ({ replace: vi.fn() }))

vi.mock('@/api/platformIdentity', () => api)
vi.mock('vue-router', () => ({ useRouter: () => router }))

describe('PlatformSetupView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.consumePlatformSetupToken.mockResolvedValue({ accepted: true })
    api.setPlatformSetupPassword.mockResolvedValue({ password_set: true })
    api.beginPlatformTotpSetup.mockResolvedValue({
      credential_id: 'credential-1',
      base32_seed: 'BASE32SEED',
    })
    api.completePlatformSetup.mockResolvedValue({
      setup_completed: true,
      recovery_codes: ['recovery-1', 'recovery-2'],
    })
    vi.spyOn(ElMessage, 'error').mockImplementation(() => undefined as never)
  })

  afterEach(() => vi.restoreAllMocks())

  it('keeps setup credentials in the page and clears prior stages after completion', async () => {
    const wrapper = shallowMount(PlatformSetupView, {
      global: { plugins: [ElementPlus] },
    })
    const state = wrapper.vm.$.setupState
    state.setupToken = 'setup-secret'

    await state.consumeToken()
    expect(state.step).toBe('password')

    state.password = 'long temporary password'
    state.passwordConfirmation = 'long temporary password'
    await state.savePassword()

    expect(api.setPlatformSetupPassword)
      .toHaveBeenCalledWith('setup-secret', 'long temporary password')
    expect(state.step).toBe('totp')
    expect(state.password).toBe('')
    expect(state.base32Seed).toBe('BASE32SEED')

    state.totpCode = '123456'
    await state.finishSetup()

    expect(api.completePlatformSetup)
      .toHaveBeenCalledWith('setup-secret', 'credential-1', '123456')
    expect(state.step).toBe('recovery')
    expect(state.setupToken).toBe('')
    expect(state.base32Seed).toBe('')
    expect(state.totpCode).toBe('')
    expect(state.recoveryCodes).toEqual(['recovery-1', 'recovery-2'])

    state.recoveryAcknowledged = true
    await state.goToLogin()
    expect(state.recoveryCodes).toEqual([])
    expect(router.replace).toHaveBeenCalledWith({ name: 'platform-login' })
    wrapper.unmount()
  })
})
