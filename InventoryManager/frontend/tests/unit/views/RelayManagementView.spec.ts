import ElementPlus from 'element-plus'
import { flushPromises, mount } from '@vue/test-utils'
import { h } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import RelayManagementView from '@/views/RelayManagementView.vue'
import type { RelayCase, RelayCaseListResponse } from '@/types/relayCase'
import {
  listRelayCases,
  refreshRelayTrackingBatch,
} from '@/api/relayCases'


vi.mock('@/api/relayCases', () => ({
  listRelayCases: vi.fn(),
  refreshRelayTracking: vi.fn(),
  refreshRelayTrackingBatch: vi.fn(),
}))


const relayCase: RelayCase = {
  case_id: 7,
  pair_key: '1:2',
  status: 'shipped',
  binding_id: 3,
  schedule_changed: false,
  overlap_days: 2,
  planned_ship_date: '2026-08-06',
  planned_receive_date: '2026-08-09',
  device: {
    id: 11,
    name: 'X300U-11',
    model: 'x300u',
    model_id: 4,
    model_display_name: 'X300U',
  },
  lens_combo: 'lens_400mm',
  accessories: [{ name: '手柄', type: 'handle', is_bundled: true }],
  successor_lens_combo: 'lens_200mm',
  successor_accessories: [{ name: '三脚架', type: 'tripod', is_bundled: false }],
  predecessor: {
    id: 1,
    start_date: '2026-08-01',
    end_date: '2026-08-05',
    buyer_id: '鹿鹿',
    customer_name: '王先生',
    customer_phone: '13800138000',
    destination: '杭州市西湖区文三路 1 号',
  },
  successor: {
    id: 2,
    start_date: '2026-08-10',
    end_date: '2026-08-14',
    buyer_id: '星星',
    customer_name: '李女士',
    customer_phone: '13900139000',
    destination: '上海市浦东新区世纪大道 2 号',
  },
  tracking: {
    number: 'SF1234567890',
    status: 'in_transit',
    summary: '运送中 · 2026-08-05 10:00:00',
    last_checked_at: '2026-08-05T10:01:00',
  },
  created_at: '2026-08-01T10:00:00',
  updated_at: '2026-08-05T10:01:00',
}


const response: RelayCaseListResponse = {
  items: [relayCase],
  total: 1,
  page: 1,
  per_page: 50,
  pages: 1,
  open_total: 1,
  filters: {
    statuses: ['pending', 'notified', 'agreed', 'shipped'],
    ship_date_from: '2026-08-02',
    ship_date_to: '2026-08-10',
  },
}


const mountView = () => mount(RelayManagementView, {
  global: {
    plugins: [ElementPlus],
    stubs: {
      RelayStatusDialog: true,
      ElTable: {
        props: ['data'],
        template: '<div data-testid="relay-wide-table"><slot /></div>',
      },
      ElTableColumn: {
        setup(_props: unknown, { slots }: { slots: Record<string, Function> }) {
          return () => h('div', slots.default?.({ row: relayCase }))
        },
      },
      teleport: true,
      transition: false,
    },
  },
})


describe('RelayManagementView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-08-05T08:00:00+08:00'))
    vi.mocked(listRelayCases).mockResolvedValue(response)
    vi.mocked(refreshRelayTrackingBatch).mockResolvedValue({
      items: [], total: 1, success_count: 1,
    })
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('defaults to open statuses and T-3 through T+5', async () => {
    const wrapper = mountView()
    await flushPromises()

    expect(listRelayCases).toHaveBeenCalledWith({
      statuses: ['pending', 'notified', 'agreed', 'shipped'],
      shipDateFrom: '2026-08-02',
      shipDateTo: '2026-08-10',
      page: 1,
      perPage: 50,
    })
    expect(wrapper.text()).toContain('寄出时间范围')
    expect(wrapper.text()).toContain('接力管理')
  })

  it('renders both customers, rental periods, equipment, dates and tracking', async () => {
    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.find('[data-testid="relay-wide-table"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('鹿鹿')
    expect(wrapper.text()).toContain('王先生')
    expect(wrapper.text()).toContain('13800138000')
    expect(wrapper.text()).toContain('杭州市西湖区文三路 1 号')
    expect(wrapper.text()).toContain('星星')
    expect(wrapper.text()).toContain('李女士')
    expect(wrapper.text()).toContain('X300U')
    expect(wrapper.text()).toContain('400MM 镜头')
    expect(wrapper.text()).toContain('手柄')
    expect(wrapper.text()).toContain('2026-08-06')
    expect(wrapper.text()).toContain('2026-08-09')
    expect(wrapper.text()).toContain('SF1234567890')
    expect(wrapper.text()).toContain('运送中')
  })

  it('batch refreshes persisted shipped cases on the current page', async () => {
    const wrapper = mountView()
    await flushPromises()

    await wrapper.get('[data-testid="batch-refresh"]').trigger('click')
    await flushPromises()

    expect(refreshRelayTrackingBatch).toHaveBeenCalledWith([7])
    expect(listRelayCases).toHaveBeenCalledTimes(2)
  })
})
