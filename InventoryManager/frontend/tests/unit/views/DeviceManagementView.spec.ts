import { createPinia, setActivePinia } from 'pinia'
import { flushPromises, shallowMount } from '@vue/test-utils'
import { ElMessageBox } from 'element-plus'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h } from 'vue'

import DeviceManagementView from '@/views/DeviceManagementView.vue'
import { useTenantStore } from '@/stores/tenant'


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

const device = {
  id: 7,
  name: 'X200U 07',
  serial_number: 'SN-007',
  model: 'x200u',
  model_id: 1,
  device_model: { display_name: 'X200 Ultra' },
  is_accessory: false,
  lifecycle_status: 'active',
  warehouse_id: 11,
  created_at: '2026-08-01T00:00:00',
  updated_at: '2026-08-01T00:00:00',
}

const ElTableColumnStub = defineComponent({
  name: 'ElTableColumn',
  props: ['prop'],
  setup(props, { slots }) {
    return () => h('div', slots.default?.({ row: device }) || String((device as any)[props.prop] || ''))
  },
})

const mountView = async () => {
  const pinia = createPinia()
  setActivePinia(pinia)
  useTenantStore().setWarehousesForSession([{
    id: 11,
    name: '深圳仓',
    province: '广东',
    city: '深圳',
  }])
  const wrapper = shallowMount(DeviceManagementView, {
    global: {
      plugins: [pinia],
      stubs: {
        WarehouseMovementDialog: true,
        ElAlert: true,
        ElButton: {
          props: ['disabled'],
          emits: ['click'],
          template: '<button :disabled="disabled" @click="$emit(\'click\')"><slot /></button>',
        },
        ElDialog: {
          props: ['modelValue'],
          template: '<div><slot /><slot name="footer" /></div>',
        },
        ElEmpty: true,
        ElForm: { template: '<form><slot /></form>' },
        ElFormItem: { template: '<div><slot /></div>' },
        ElIcon: true,
        ElInput: true,
        ElOption: true,
        ElPagination: true,
        ElRadioButton: { template: '<span><slot /></span>' },
        ElRadioGroup: { template: '<div><slot /></div>' },
        ElSelect: { template: '<select><slot /></select>' },
        ElTable: { template: '<div><slot /></div>' },
        ElTableColumn: ElTableColumnStub,
        ElTag: { template: '<span><slot /></span>' },
      },
      directives: { loading: () => undefined },
    },
  })
  await flushPromises()
  return wrapper
}

describe('DeviceManagementView', () => {
  beforeEach(() => {
    axiosDelete.mockReset()
    axiosGet.mockReset()
    axiosPost.mockReset()
    axiosPut.mockReset()
    axiosGet.mockImplementation((url: string) => {
      if (url === '/api/device-models') {
        return Promise.resolve({
          data: {
            success: true,
            data: [{ id: 1, name: 'x200u', display_name: 'X200 Ultra' }],
          },
        })
      }
      return Promise.resolve({
        data: {
          devices: [device],
          total: 1,
          pages: 1,
          current_page: 1,
          per_page: 50,
        },
      })
    })
    axiosPost.mockResolvedValue({ data: { success: true } })
    axiosPut.mockResolvedValue({ data: { success: true } })
    axiosDelete.mockResolvedValue({ data: { success: true } })
  })

  it('lists devices for the active warehouse and exposes edit and delete actions', async () => {
    const wrapper = await mountView()

    expect(wrapper.text()).toContain('设备管理')
    expect(wrapper.text()).toContain('深圳仓 · 共 1 台设备与附件')
    expect(wrapper.text()).toContain('X200U 07')
    expect(wrapper.text()).toContain('SN-007')
    expect(wrapper.text()).toContain('编辑')
    expect(wrapper.text()).toContain('删除')
    expect(axiosGet).toHaveBeenCalledWith('/api/devices', {
      params: expect.objectContaining({ warehouse_id: 11, per_page: 50 }),
    })
  })

  it('creates a device in the selected warehouse', async () => {
    const wrapper = await mountView()
    const vm = wrapper.vm as any

    await wrapper.get('[data-testid="add-device"]').trigger('click')
    Object.assign(vm.form, {
      name: 'X200U 08',
      serial_number: 'SN-008',
      model: 'x200u',
      model_id: 1,
      is_accessory: false,
    })
    await vm.submitEditor()

    expect(axiosPost).toHaveBeenCalledWith('/api/devices', expect.objectContaining({
      name: 'X200U 08',
      serial_number: 'SN-008',
      warehouse_id: 11,
    }))
  })

  it('asks for confirmation before deleting a device', async () => {
    vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue('confirm')
    const wrapper = await mountView()

    await (wrapper.vm as any).deleteDevice(device)

    expect(ElMessageBox.confirm).toHaveBeenCalledWith(
      expect.stringContaining('SN-007'),
      '删除设备',
      expect.objectContaining({ type: 'warning' }),
    )
    expect(axiosDelete).toHaveBeenCalledWith('/api/devices/7')
  })
})
