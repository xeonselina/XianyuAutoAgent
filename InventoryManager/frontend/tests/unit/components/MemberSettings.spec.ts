import { createPinia, setActivePinia } from 'pinia'
import { flushPromises, shallowMount } from '@vue/test-utils'
import { ElMessage } from 'element-plus'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import MemberSettings from '@/components/settings/MemberSettings.vue'
import { useAuthStore } from '@/stores/auth'


const apiMocks = vi.hoisted(() => ({
  createMember: vi.fn(),
  listMembers: vi.fn(),
  resetMemberPassword: vi.fn(),
  updateMember: vi.fn(),
}))

vi.mock('@/api/settings', () => apiMocks)

const members = [
  {
    id: 1,
    phone: '+8613800138000',
    role: 'admin' as const,
    status: 'active' as const,
  },
  {
    id: 2,
    phone: '+8613900139000',
    role: 'operator' as const,
    status: 'active' as const,
  },
]

const mountSettings = async () => {
  const pinia = createPinia()
  setActivePinia(pinia)
  useAuthStore().member = members[0]
  const wrapper = shallowMount(MemberSettings, {
    global: {
      plugins: [pinia],
      directives: { loading: () => undefined },
      stubs: {
        ElAlert: true,
        ElButton: true,
        ElDialog: true,
        ElForm: true,
        ElFormItem: true,
        ElInput: true,
        ElOption: true,
        ElSelect: true,
        ElSwitch: true,
        ElTable: true,
        ElTableColumn: true,
      },
    },
  })
  await flushPromises()
  return wrapper
}

describe('MemberSettings', () => {
  beforeEach(() => {
    Object.values(apiMocks).forEach((mock) => mock.mockReset())
    apiMocks.listMembers.mockResolvedValue(members)
    apiMocks.createMember.mockResolvedValue(members[1])
    apiMocks.resetMemberPassword.mockResolvedValue(members[1])
    apiMocks.updateMember.mockResolvedValue(members[1])
    vi.spyOn(ElMessage, 'success').mockImplementation(() => undefined as never)
    vi.spyOn(ElMessage, 'warning').mockImplementation(() => undefined as never)
    vi.spyOn(ElMessage, 'error').mockImplementation(() => undefined as never)
  })

  it('creates a member with the administrator-defined initial password', async () => {
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    vm.form.phone = '13900139000'
    vm.form.role = 'operator'
    vm.form.initialPassword = 'Member123'
    vm.form.confirmPassword = 'Member123'

    await vm.add()

    expect(apiMocks.createMember).toHaveBeenCalledWith(
      '13900139000',
      'operator',
      'Member123',
    )
    expect(vm.form.initialPassword).toBe('')
    expect(vm.form.confirmPassword).toBe('')
    expect(ElMessage.success).toHaveBeenCalledWith('成员已添加')
  })

  it('rejects a seven-character initial password before calling the API', async () => {
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    vm.form.phone = '13900139000'
    vm.form.initialPassword = 'short7!'
    vm.form.confirmPassword = 'short7!'

    await vm.add()

    expect(apiMocks.createMember).not.toHaveBeenCalled()
    expect(ElMessage.warning).toHaveBeenCalledWith(
      '初始密码必须为 8 至 128 个字符',
    )
  })

  it('resets another member password and explains the forced login', async () => {
    const wrapper = await mountSettings()
    const vm = wrapper.vm as any
    vm.openPasswordReset(members[1])
    vm.resetForm.newPassword = 'Reset123'
    vm.resetForm.confirmPassword = 'Reset123'

    await vm.resetPassword()

    expect(apiMocks.resetMemberPassword).toHaveBeenCalledWith(2, 'Reset123')
    expect(vm.resetTarget).toBeNull()
    expect(ElMessage.success).toHaveBeenCalledWith(
      '密码已重置，该成员需重新登录',
    )
  })
})
