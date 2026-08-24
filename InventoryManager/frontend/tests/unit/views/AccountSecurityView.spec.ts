import ElementPlus, { ElMessage, ElMessageBox } from 'element-plus'
import { flushPromises, shallowMount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import AccountSecurityView from '@/views/AccountSecurityView.vue'


const api = vi.hoisted(() => ({
  clearTenantCsrfToken: vi.fn(),
  confirmTenantPhoneChange: vi.fn(),
  listTenantSessions: vi.fn(),
  logoutCurrentSession: vi.fn(),
  revokeAllTenantSessions: vi.fn(),
  revokeTenantSession: vi.fn(),
  requestTenantPhoneChange: vi.fn(),
}))
const router = vi.hoisted(() => ({ back: vi.fn(), replace: vi.fn() }))

vi.mock('@/api/tenantIdentity', () => api)
vi.mock('vue-router', () => ({ useRouter: () => router }))

const current = {
  session_id: '11111111-1111-4111-8111-111111111111',
  device_summary: '当前浏览器',
  created_at: '2026-08-22T08:00:00Z',
  last_seen_at: '2026-08-22T09:00:00Z',
  is_current: true,
}
const other = {
  session_id: '22222222-2222-4222-8222-222222222222',
  device_summary: '办公室浏览器',
  created_at: '2026-08-21T08:00:00Z',
  last_seen_at: '2026-08-22T07:00:00Z',
  is_current: false,
}

describe('AccountSecurityView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.listTenantSessions.mockResolvedValue([current, other])
    api.logoutCurrentSession.mockResolvedValue({ logged_out: true, revoked: true })
    api.revokeTenantSession.mockResolvedValue({
      revoked: true,
      current_session_revoked: false,
    })
    api.revokeAllTenantSessions.mockResolvedValue({
      revoked_count: 2,
      all_sessions_revoked: true,
    })
    api.requestTenantPhoneChange.mockResolvedValue({
      intent_id: 'action-1',
      old_challenge_id: 'old-1',
      new_challenge_id: 'new-1',
      expires_at: '2026-08-23T04:00:00Z',
      replayed: false,
    })
    api.confirmTenantPhoneChange.mockResolvedValue({
      phone_changed: true,
      login_required: true,
    })
    vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue('confirm')
    vi.spyOn(ElMessage, 'success').mockImplementation(() => undefined as never)
    vi.spyOn(ElMessage, 'error').mockImplementation(() => undefined as never)
  })

  afterEach(() => vi.restoreAllMocks())

  const mountView = async () => {
    const wrapper = shallowMount(AccountSecurityView, {
      global: {
        plugins: [ElementPlus],
        directives: { loading: () => undefined },
      },
    })
    await flushPromises()
    return wrapper
  }

  it('loads only the backend-projected device rows', async () => {
    const wrapper = await mountView()

    expect(api.listTenantSessions).toHaveBeenCalledOnce()
    expect(wrapper.vm.$.setupState.sessions).toEqual([current, other])
    expect(wrapper.text()).not.toContain('token_digest')
  })

  it('revokes another device without ending the caller session', async () => {
    const wrapper = await mountView()

    await wrapper.vm.$.setupState.revokeOne(other)

    expect(api.revokeTenantSession).toHaveBeenCalledWith(other.session_id)
    expect(api.logoutCurrentSession).not.toHaveBeenCalled()
    expect(wrapper.vm.$.setupState.sessions).toEqual([current])
  })

  it('clears browser CSRF state after current-device logout', async () => {
    const wrapper = await mountView()

    await wrapper.vm.$.setupState.revokeOne(current)

    expect(api.logoutCurrentSession).toHaveBeenCalledOnce()
    expect(api.clearTenantCsrfToken).toHaveBeenCalledOnce()
    expect(router.replace).toHaveBeenCalledWith({ name: 'tenant-login' })
  })

  it('keeps one action id across dual-code phone confirmation', async () => {
    const wrapper = await mountView()
    wrapper.vm.$.setupState.newPhone = '13900139000'
    await flushPromises()

    await wrapper.vm.$.setupState.requestPhoneCodes()
    const actionId = api.requestTenantPhoneChange.mock.calls[0][1]
    wrapper.vm.$.setupState.oldPhoneCode = '123456'
    wrapper.vm.$.setupState.newPhoneCode = '654321'
    await wrapper.vm.$.setupState.confirmPhoneChange()

    expect(api.confirmTenantPhoneChange).toHaveBeenCalledWith({
      new_phone: '13900139000',
      action_id: actionId,
      old_challenge_id: 'old-1',
      old_code: '123456',
      new_challenge_id: 'new-1',
      new_code: '654321',
    })
    expect(api.clearTenantCsrfToken).toHaveBeenCalledOnce()
    expect(router.replace).toHaveBeenCalledWith({ name: 'tenant-login' })
  })
})
