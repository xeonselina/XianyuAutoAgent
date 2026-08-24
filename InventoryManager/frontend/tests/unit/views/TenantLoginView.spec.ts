import ElementPlus, { ElMessage } from 'element-plus'
import { flushPromises, shallowMount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import TenantLoginView from '@/views/TenantLoginView.vue'


const api = vi.hoisted(() => ({
  requestTenantLoginCode: vi.fn(),
  verifyTenantLoginCode: vi.fn(),
}))
const router = vi.hoisted(() => ({ replace: vi.fn() }))

vi.mock('@/api/tenantIdentity', () => api)
vi.mock('vue-router', () => ({ useRouter: () => router }))

describe('TenantLoginView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.useFakeTimers()
    api.requestTenantLoginCode.mockResolvedValue({
      challenge_id: 'challenge-1',
      expires_in_seconds: 300,
      resend_after_seconds: 60,
    })
    api.verifyTenantLoginCode.mockResolvedValue({
      effective_gate: 'active',
    })
    vi.spyOn(ElMessage, 'success').mockImplementation(() => undefined as never)
    vi.spyOn(ElMessage, 'error').mockImplementation(() => undefined as never)
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  it('requests and verifies one in-memory challenge then routes active login', async () => {
    const wrapper = shallowMount(TenantLoginView, {
      global: { plugins: [ElementPlus] },
    })
    const state = wrapper.vm.$.setupState
    state.phone = '13800138001'

    await state.sendCode()
    state.code = '123456'
    await state.verifyCode()
    await flushPromises()

    expect(api.requestTenantLoginCode).toHaveBeenCalledWith('13800138001')
    expect(api.verifyTenantLoginCode).toHaveBeenCalledWith({
      phone: '13800138001',
      challenge_id: 'challenge-1',
      code: '123456',
      device_name: '桌面浏览器',
    })
    expect(router.replace).toHaveBeenCalledWith({ name: 'gantt' })
    wrapper.unmount()
  })

  it('routes a restricted login to the tenant status shell', async () => {
    api.verifyTenantLoginCode.mockResolvedValue({
      effective_gate: 'suspended',
    })
    const wrapper = shallowMount(TenantLoginView, {
      global: { plugins: [ElementPlus] },
    })
    const state = wrapper.vm.$.setupState
    state.phone = '13800138001'
    await state.sendCode()
    state.code = '123456'

    await state.verifyCode()

    expect(router.replace).toHaveBeenCalledWith({ name: 'tenant-status' })
    wrapper.unmount()
  })
})
