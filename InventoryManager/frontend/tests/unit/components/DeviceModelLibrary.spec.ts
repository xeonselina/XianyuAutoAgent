import { createPinia, setActivePinia } from 'pinia'
import { flushPromises, shallowMount } from '@vue/test-utils'
import { ElMessageBox } from 'element-plus'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import DeviceModelLibrary from '@/components/DeviceModelLibrary.vue'
import { useAuthStore } from '@/stores/auth'


const { axiosDelete, axiosGet, axiosPost, axiosPut } = vi.hoisted(() => ({
  axiosDelete: vi.fn(),
  axiosGet: vi.fn(),
  axiosPost: vi.fn(),
  axiosPut: vi.fn(),
}))

vi.mock('axios', () => ({
  default: {
    delete: axiosDelete,
    get: axiosGet,
    post: axiosPost,
    put: axiosPut,
  },
}))

const model = {
  id: 1,
  name: 'x200u',
  display_name: '富士 X200U',
  description: '主力型号',
  is_active: true,
  is_accessory: false,
  parent_model_id: null,
  default_accessories: ['电池'],
  device_value: 12000,
  device_count: 3,
  accessory_count: 0,
  allowed_lens_combos: ['lens_200mm', 'bare'],
  default_lens_combo: 'lens_200mm',
  rental_packages: [
    {
      id: 'pkg_2470',
      name: '机身 + 24-70',
      is_active: true,
      items: [{ name: '24-70 镜头', qty: 1 }],
    },
  ],
  default_rental_package_id: 'pkg_2470',
  accessories: [],
  created_at: '2026-08-01T00:00:00',
  updated_at: '2026-08-01T00:00:00',
}

const mountLibrary = async () => {
  const pinia = createPinia()
  setActivePinia(pinia)
  useAuthStore().member = {
    id: 1,
    phone: '+8613800138000',
    role: 'admin',
    status: 'active',
  }
  const wrapper = shallowMount(DeviceModelLibrary, {
    global: {
      plugins: [pinia],
      directives: {
        loading: () => undefined,
      },
      stubs: {
        ElAlert: true,
        ElButton: true,
        ElCheckbox: true,
        ElCheckboxGroup: true,
        ElDialog: true,
        ElEmpty: true,
        ElForm: true,
        ElFormItem: true,
        ElInput: true,
        ElInputNumber: true,
        ElOption: true,
        ElRadio: true,
        ElRadioButton: true,
        ElRadioGroup: true,
        ElSelect: true,
        ElSwitch: true,
        ElTable: true,
        ElTableColumn: true,
        ElTag: true,
      },
    },
  })
  await flushPromises()
  return wrapper
}

describe('DeviceModelLibrary', () => {
  beforeEach(() => {
    axiosDelete.mockReset()
    axiosGet.mockReset()
    axiosPost.mockReset()
    axiosPut.mockReset()
    axiosGet.mockResolvedValue({
      data: {
        success: true,
        data: {
          models: [model],
          legacy_groups: [{
            normalized_model: 'legacy camera',
            model: 'Legacy Camera',
            device_count: 2,
          }],
        },
      },
    })
    axiosPost.mockResolvedValue({ data: { success: true } })
    axiosPut.mockResolvedValue({ data: { success: true } })
    axiosDelete.mockResolvedValue({ data: { success: true } })
  })

  it('loads canonical models and unresolved legacy groups', async () => {
    const wrapper = await mountLibrary()
    const vm = wrapper.vm as any

    expect(axiosGet).toHaveBeenCalledWith('/api/device-models/library')
    expect(vm.models).toHaveLength(1)
    expect(vm.legacyGroups).toHaveLength(1)
    expect(vm.filteredModels[0].display_name).toBe('富士 X200U')
  })

  it('creates a canonical model', async () => {
    const wrapper = await mountLibrary()
    const vm = wrapper.vm as any
    vm.openCreate()
    Object.assign(vm.form, {
      name: 'x300pro',
      display_name: '富士 X300 Pro',
      description: '新型号',
      device_value: 15000,
      is_accessory: false,
      is_active: true,
      default_accessories_text: '电池\n充电器',
      rental_packages: [
        {
          client_id: 'camera_2470',
          name: '机身 + 24-70',
          is_active: true,
          items: [
            { name: '24-70 镜头', qty: 1 },
            { name: '相机电池', qty: 2 },
          ],
        },
      ],
      default_rental_package_id: 'camera_2470',
    })

    await vm.saveModel()

    expect(axiosPost).toHaveBeenCalledWith('/api/device-models', expect.objectContaining({
      name: 'x300pro',
      display_name: '富士 X300 Pro',
      default_accessories: ['电池', '充电器'],
      rental_packages: [{
        client_id: 'camera_2470',
        name: '机身 + 24-70',
        is_active: true,
        items: [
          { name: '24-70 镜头', qty: 1 },
          { name: '相机电池', qty: 2 },
        ],
      }],
      default_rental_package_id: 'camera_2470',
    }))
  })

  it('copies editable model configuration with independent package IDs', async () => {
    const wrapper = await mountLibrary()
    const vm = wrapper.vm as any

    vm.openCopy(vm.models[0])

    expect(vm.editorMode).toBe('copy')
    expect(vm.form.id).toBeUndefined()
    expect(vm.form.name).toBe('x200u-copy')
    expect(vm.form.display_name).toBe('富士 X200U（副本）')
    expect(vm.form.device_value).toBe(12000)
    expect(vm.form.default_accessories_text).toBe('电池')
    expect(vm.form.rental_packages).toEqual([
      {
        client_id: expect.stringMatching(/^new_/),
        name: '机身 + 24-70',
        is_active: true,
        items: [{ name: '24-70 镜头', qty: 1 }],
      },
    ])
    const copiedPackageId = vm.form.rental_packages[0].client_id
    expect(copiedPackageId).not.toBe('pkg_2470')
    expect(vm.form.default_rental_package_id).toBe(copiedPackageId)

    vm.form.rental_packages[0].items[0].name = '复制后的镜头'
    expect(model.rental_packages[0].items[0].name).toBe('24-70 镜头')
    await vm.saveModel()

    expect(axiosPost).toHaveBeenCalledWith('/api/device-models', expect.objectContaining({
      name: 'x200u-copy',
      display_name: '富士 X200U（副本）',
      rental_packages: [{
        client_id: copiedPackageId,
        name: '机身 + 24-70',
        is_active: true,
        items: [{ name: '复制后的镜头', qty: 1 }],
      }],
      default_rental_package_id: copiedPackageId,
    }))
  })

  it('increments the suggested copy code when prior copies exist', async () => {
    axiosGet.mockResolvedValueOnce({
      data: {
        success: true,
        data: {
          models: [
            model,
            { ...model, id: 2, name: 'x200u-copy' },
            { ...model, id: 3, name: 'x200u-copy-2' },
          ],
          legacy_groups: [],
        },
      },
    })
    const wrapper = await mountLibrary()
    const vm = wrapper.vm as any

    vm.openCopy(vm.models[0])

    expect(vm.form.name).toBe('x200u-copy-3')
  })

  it('assigns one legacy group to a canonical model after confirmation', async () => {
    vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue('confirm')
    const wrapper = await mountLibrary()
    const vm = wrapper.vm as any
    vm.legacyAssignments['legacy camera'] = 1

    await vm.assignLegacy(vm.legacyGroups[0])

    expect(axiosPost).toHaveBeenCalledWith('/api/device-models/assign-legacy', {
      legacy_model: 'legacy camera',
      model_id: 1,
    })
  })
})
