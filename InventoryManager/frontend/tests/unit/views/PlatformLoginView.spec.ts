import ElementPlus, { ElMessage } from 'element-plus'
import { shallowMount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import PlatformLoginView from '@/views/PlatformLoginView.vue'


const api = vi.hoisted(() => ({ loginPlatformAdmin: vi.fn() }))
const router = vi.hoisted(() => ({ push: vi.fn(), replace: vi.fn() }))

vi.mock('@/api/platformIdentity', () => api)
vi.mock('vue-router', () => ({ useRouter: () => router }))

describe('PlatformLoginView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.loginPlatformAdmin.mockResolvedValue({
      session_id: 'session-1',
      role: 'platform_admin',
      mfa_method: 'totp',
    })
    vi.spyOn(ElMessage, 'error').mockImplementation(() => undefined as never)
  })

  afterEach(() => vi.restoreAllMocks())

  it('submits password and factor from component memory then clears both', async () => {
    const wrapper = shallowMount(PlatformLoginView, {
      global: { plugins: [ElementPlus] },
    })
    const state = wrapper.vm.$.setupState
    state.username = 'root.admin'
    state.password = 'temporary password'
    state.factor = '123456'

    await state.submitLogin()

    expect(api.loginPlatformAdmin).toHaveBeenCalledWith({
      username: 'root.admin',
      password: 'temporary password',
      factor_method: 'totp',
      factor: '123456',
      device_name: '桌面浏览器',
    })
    expect(state.password).toBe('')
    expect(state.factor).toBe('')
    expect(router.replace).toHaveBeenCalledWith({ name: 'platform-security' })
    wrapper.unmount()
  })
})
