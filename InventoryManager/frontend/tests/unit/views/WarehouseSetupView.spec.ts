import ElementPlus, { ElMessage } from 'element-plus'
import { flushPromises, shallowMount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import WarehouseSetupView from '@/views/WarehouseSetupView.vue'


const api = vi.hoisted(() => ({
  getDefaultWarehouseSetup: vi.fn(),
  setupDefaultWarehouse: vi.fn(),
}))
const router = vi.hoisted(() => ({ replace: vi.fn() }))

vi.mock('@/api/warehouse', () => api)
vi.mock('vue-router', () => ({ useRouter: () => router }))

describe('WarehouseSetupView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.getDefaultWarehouseSetup.mockResolvedValue({
      id: 1,
      name: null,
      setup_state: 'pending',
      contact_name: null,
      contact_phone: '13800138000',
      province: null,
      city: null,
      district: null,
      address_detail: null,
    })
    api.setupDefaultWarehouse.mockResolvedValue({
      id: 1,
      setup_state: 'ready',
    })
    vi.spyOn(ElMessage, 'success').mockImplementation(() => undefined as never)
    vi.spyOn(ElMessage, 'error').mockImplementation(() => undefined as never)
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('prefills the registration phone and submits every confirmed field', async () => {
    const wrapper = shallowMount(WarehouseSetupView, {
      global: {
        plugins: [ElementPlus],
        directives: { loading: () => undefined },
      },
    })
    await flushPromises()

    const state = wrapper.vm.$.setupState
    expect(state.form.contact_phone).toBe('13800138000')
    state.form.contact_name = '负责人'
    state.form.province = '广东省'
    state.form.city = '深圳市'
    state.form.district = '南山区'
    state.form.address_detail = '测试路 1 号'

    await state.submit()

    expect(api.setupDefaultWarehouse).toHaveBeenCalledWith({
      name: '默认仓库',
      contact_name: '负责人',
      contact_phone: '13800138000',
      province: '广东省',
      city: '深圳市',
      district: '南山区',
      address_detail: '测试路 1 号',
    })
    expect(router.replace).toHaveBeenCalledWith('/')
  })
})
