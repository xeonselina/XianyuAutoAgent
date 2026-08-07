import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { getLatestRentalByDeviceName } from '@/api/inspection'
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
})

