import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { createInspection, getLatestRentalByDeviceName } from '@/api/inspection'
import { useInspectionStore } from '@/stores/inspection'

vi.mock('@/api/inspection', () => ({
  getLatestRentalByDeviceId: vi.fn(),
  getLatestRentalByDeviceName: vi.fn(),
  createInspection: vi.fn(),
  getInspectionById: vi.fn(),
  updateInspection: vi.fn(),
  getInspectionList: vi.fn(),
}))

describe('inspection checklist damage defaults', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('checks regular items by default but leaves damage handling unchecked', async () => {
    vi.mocked(getLatestRentalByDeviceName).mockResolvedValue({
      success: true,
      data: {
        rental: {
          id: 19,
          device_id: 4,
          start_date: '2026-08-01',
          end_date: '2026-08-05',
          customer_name: '测试客户',
          status: 'returned',
          includes_handle: false,
          includes_lens_mount: false,
          photo_transfer: false,
          created_at: '2026-08-01T00:00:00',
          updated_at: '2026-08-06T00:00:00',
        },
        checklist: [
          { name: '屏幕外观', order: 1 },
          {
            name: '处理用户反馈：屏幕右下角碎裂',
            order: 2,
            default_checked: false,
          },
        ],
      },
    } as any)
    const store = useInspectionStore()

    const success = await store.fetchLatestRentalByDeviceName('2001')

    expect(success).toBe(true)
    expect(store.checkItems.map(item => item.is_checked)).toEqual([true, false])
  })

  it('submits the selected warehouse and type-level receipt without unit IDs', async () => {
    vi.mocked(getLatestRentalByDeviceName).mockResolvedValue({
      success: true,
      data: {
        rental: {
          id: 21,
          device_id: 5,
          start_date: '2026-08-01',
          end_date: '2026-08-05',
          customer_name: '测试客户',
          status: 'returned',
          includes_handle: false,
          includes_lens_mount: false,
          photo_transfer: false,
          created_at: '2026-08-01T00:00:00',
          updated_at: '2026-08-06T00:00:00',
        },
        checklist: [{ name: '屏幕外观', order: 1 }],
        warehouses: [
          {
            id: 8,
            name: '验货仓',
            is_default: false,
            province: '广东省',
            city: '深圳市',
            district: '南山区',
            address_detail: '测试路 8 号',
          },
        ],
        selected_warehouse_id: 8,
        accessory_receipts: [
          {
            accessory_type_id: 3,
            type_code: 'tripod',
            display_name: '三脚架',
            travels_with_device: true,
            outcome: 'received_normal',
          },
        ],
      },
    } as any)
    vi.mocked(createInspection).mockResolvedValue({
      success: true,
      data: {
        id: 31,
        rental_id: 21,
        device_id: 5,
        status: 'abnormal',
        warehouse_id: 8,
        created_at: '2026-08-22T16:30:00',
        updated_at: '2026-08-22T16:30:00',
        check_items: [],
      },
    })
    const store = useInspectionStore()

    expect(await store.fetchLatestRentalByDeviceName('2001')).toBe(true)
    store.accessoryReceipts[0].outcome = 'missing'
    expect(await store.submitInspection()).toBe(true)

    const payload = vi.mocked(createInspection).mock.calls[0][0]
    expect(payload).toEqual({
      rental_id: 21,
      device_id: 5,
      warehouse_id: 8,
      check_items: [
        { name: '屏幕外观', is_checked: true, order: 1 },
      ],
      accessory_receipts: [
        { accessory_type_id: 3, outcome: 'missing' },
      ],
    })
    expect(JSON.stringify(payload)).not.toContain('unit')
  })
})
