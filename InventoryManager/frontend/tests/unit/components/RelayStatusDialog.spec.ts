import ElementPlus, { ElSelect } from 'element-plus'
import { flushPromises, mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import RelayStatusDialog from '@/components/relay/RelayStatusDialog.vue'
import type { RelayCase } from '@/types/relayCase'
import { updateRelayCase } from '@/api/relayCases'


vi.mock('@/api/relayCases', () => ({
  updateRelayCase: vi.fn(),
}))


const baseCase = {
  case_id: null,
  pair_key: '1:2',
  status: 'pending',
  binding_id: null,
  schedule_changed: false,
  overlap_days: 2,
  planned_ship_date: '2026-08-06',
  planned_receive_date: '2026-08-09',
  predecessor: {
    id: 1,
    start_date: '2026-08-01',
    end_date: '2026-08-05',
    buyer_id: '鹿鹿',
    customer_name: '王先生',
    customer_phone: '13800138000',
    destination: '杭州',
  },
  successor: {
    id: 2,
    start_date: '2026-08-10',
    end_date: '2026-08-14',
    buyer_id: '星星',
    customer_name: '李女士',
    customer_phone: '13900139000',
    destination: '上海',
  },
  device: {
    id: 1,
    name: 'X300U-1',
    model: 'x300u',
    model_id: 1,
    model_display_name: 'X300U',
  },
  lens_combo: 'lens_400mm',
  accessories: [],
  successor_lens_combo: 'lens_400mm',
  successor_accessories: [],
  tracking: {
    number: null,
    status: null,
    summary: null,
    last_checked_at: null,
  },
  created_at: null,
  updated_at: null,
} satisfies RelayCase


const mountDialog = (relayCase: RelayCase = baseCase) => mount(
  RelayStatusDialog,
  {
    props: { modelValue: true, relayCase },
    global: {
      plugins: [ElementPlus],
      stubs: {
        ElDialog: {
          props: ['modelValue'],
          template: '<div v-if="modelValue"><slot /><slot name="footer" /></div>',
        },
        teleport: true,
        transition: false,
      },
    },
  },
)


describe('RelayStatusDialog', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(updateRelayCase).mockResolvedValue({
      case_id: 7,
      predecessor_rental_id: 1,
      successor_rental_id: 2,
      status: 'shipped',
      sf_tracking_number: 'SF123',
      tracking: {
        number: 'SF123', status: 'unknown', summary: null, last_checked_at: null,
      },
      notified_at: null,
      agreed_at: null,
      shipped_at: null,
      completed_at: null,
    })
  })

  it('requires a tracking number before saving shipped', async () => {
    const wrapper = mountDialog()
    wrapper.findComponent(ElSelect).vm.$emit('update:modelValue', 'shipped')
    await wrapper.get('[data-testid="save-relay-status"]').trigger('click')

    expect(updateRelayCase).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('请输入顺丰运单号')
  })

  it('saves shipped with the pair and tracking number', async () => {
    const wrapper = mountDialog()
    wrapper.findComponent(ElSelect).vm.$emit('update:modelValue', 'shipped')
    await nextTick()
    await wrapper.get('[data-testid="tracking-number"]').setValue('SF123')
    await wrapper.get('[data-testid="save-relay-status"]').trigger('click')
    await flushPromises()

    expect(updateRelayCase).toHaveBeenCalledWith(1, 2, {
      status: 'shipped',
      sf_tracking_number: 'SF123',
    })
    expect(wrapper.emitted('saved')).toHaveLength(1)
  })
})
