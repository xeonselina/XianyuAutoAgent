import ElementPlus, { ElMessage } from 'element-plus'
import { flushPromises, shallowMount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import WarehouseManagementView from '@/views/WarehouseManagementView.vue'


const api = vi.hoisted(() => ({
  listWarehouses: vi.fn(),
  listWarehouseDevices: vi.fn(),
  listWarehouseDeviceModels: vi.fn(),
  createWarehouseMainDevice: vi.fn(),
  getWarehousePreferences: vi.fn(),
  setWarehousePreference: vi.fn(),
  createWarehouse: vi.fn(),
  updateWarehouse: vi.fn(),
  setDefaultWarehouse: vi.fn(),
  deactivateWarehouse: vi.fn(),
  previewDeviceMove: vi.fn(),
  confirmDeviceMove: vi.fn(),
}))

vi.mock('@/api/warehouse', () => api)
vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn() }),
}))

const warehouses = [
  {
    id: 1,
    warehouse_uuid: 'warehouse-1',
    name: '原仓',
    status: 'active',
    setup_state: 'ready',
    is_default: true,
    contact_name: '负责人',
    contact_phone: '13800138000',
    province: '广东省',
    city: '深圳市',
    district: '南山区',
    address_detail: '原仓地址',
  },
  {
    id: 2,
    warehouse_uuid: 'warehouse-2',
    name: '目标仓',
    status: 'active',
    setup_state: 'ready',
    is_default: false,
    contact_name: '负责人',
    contact_phone: '13800138000',
    province: '浙江省',
    city: '杭州市',
    district: '余杭区',
    address_detail: '目标仓地址',
  },
] as any

const preview = {
  device: { id: 7, name: '主设备', warehouse_id: 1 },
  current_warehouse: warehouses[0],
  target_warehouse: warehouses[1],
  is_same_warehouse: false,
  affected_rental_ids: [31],
  affected_rentals: [
    {
      rental_id: 31,
      order_number: 'ORDER-31',
      customer_start_date: '2026-09-02',
      customer_end_date: '2026-09-05',
      logistics_days: 1,
      planned_ship_out_date: '2026-09-01',
      planned_return_date: '2026-09-06',
      affected_accessory_types: [
        { accessory_type_id: 3, name: '三脚架' },
      ],
    },
  ],
  revision: 'a'.repeat(64),
  preserves_logistics_facts: true,
} as any

describe('WarehouseManagementView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.listWarehouses.mockResolvedValue(warehouses)
    api.listWarehouseDevices.mockResolvedValue([
      {
        id: 7,
        name: '主设备',
        serial_number: 'SN-7',
        model: 'x300u',
        warehouse_id: 1,
      },
    ])
    api.listWarehouseDeviceModels.mockResolvedValue([
      { id: 9, name: 'x300u', display_name: 'VIVO X300 Ultra' },
    ])
    api.createWarehouseMainDevice.mockResolvedValue({
      id: 8,
      name: '新主设备',
      serial_number: 'SN-8',
      model: 'x300u',
      model_id: 9,
      warehouse_id: 2,
    })
    api.getWarehousePreferences.mockResolvedValue({ booking: 1 })
    api.setWarehousePreference.mockResolvedValue({
      scene: 'booking',
      warehouse_id: 2,
    })
    api.previewDeviceMove.mockResolvedValue(preview)
    api.confirmDeviceMove.mockResolvedValue({
      device_id: 7,
      from_warehouse_id: 1,
      to_warehouse_id: 2,
      movement_id: 'movement-1',
      affected_rental_ids: [31],
      accessory_fulfillment: [
        {
          rental_id: 31,
          accessory_type_id: 3,
          accessory_name: '三脚架',
          status: 'shortage',
        },
      ],
    })
    vi.spyOn(ElMessage, 'success').mockImplementation(() => undefined as never)
    vi.spyOn(ElMessage, 'warning').mockImplementation(() => undefined as never)
    vi.spyOn(ElMessage, 'error').mockImplementation(() => undefined as never)
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('previews immutable logistics facts and confirms against the revision', async () => {
    const wrapper = shallowMount(WarehouseManagementView, {
      global: {
        plugins: [ElementPlus],
        stubs: {
          teleport: true,
          transition: false,
          ElTable: { template: '<div />' },
          ElTableColumn: { template: '<div />' },
        },
        directives: { loading: () => undefined },
      },
    })
    await flushPromises()

    const state = wrapper.vm.$.setupState
    state.moveForm.deviceId = 7
    state.moveForm.targetWarehouseId = 2
    state.moveForm.note = '按实际位置调仓'
    await state.loadPreview()

    expect(api.previewDeviceMove).toHaveBeenCalledWith({
      device_id: 7,
      target_warehouse_id: 2,
    })
    expect(state.preview.preserves_logistics_facts).toBe(true)

    await state.confirmMove()

    expect(api.confirmDeviceMove).toHaveBeenCalledWith({
      device_id: 7,
      target_warehouse_id: 2,
      expected_current_warehouse_id: 1,
      expected_preview_revision: 'a'.repeat(64),
      confirmed: true,
      note: '按实际位置调仓',
    })
    expect(ElMessage.warning).toHaveBeenCalledWith(
      '调仓已完成；订单 #31 的附件仍然不足'
    )

    state.deviceForm.name = '新主设备'
    state.deviceForm.serial_number = 'SN-8'
    state.deviceForm.model_id = 9
    state.deviceForm.warehouse_id = 2
    await state.submitDevice()
    expect(api.createWarehouseMainDevice).toHaveBeenCalledWith({
      name: '新主设备',
      serial_number: 'SN-8',
      model_id: 9,
      warehouse_id: 2,
    })
  })
})
