import ElementPlus, { ElMessage, ElSelect } from 'element-plus'
import { flushPromises, mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import ManualRelayDialog from '@/components/relay/ManualRelayDialog.vue'
import {
  createManualRelayCase,
  listManualRelayOptions,
} from '@/api/relayCases'
import type { ManualRelayOption } from '@/types/relayCase'


vi.mock('@/api/relayCases', () => ({
  createManualRelayCase: vi.fn(),
  listManualRelayOptions: vi.fn(),
}))


const option: ManualRelayOption = {
  device: {
    id: 11,
    name: 'X300U-11',
    model: 'x300u',
    model_id: 4,
    model_display_name: 'X300U',
  },
  predecessor: {
    id: 101,
    status: 'returned',
    start_date: '2026-08-01',
    end_date: '2026-08-12',
    ship_out_time: '2026-07-31T19:00:00',
    ship_in_time: '2026-08-13T12:00:00',
    buyer_id: '鹿鹿',
    customer_name: '王先生',
    customer_phone: '13800138000',
    destination: '杭州市西湖区',
  },
  successor: {
    id: 102,
    status: 'not_shipped',
    start_date: '2026-08-15',
    end_date: '2026-08-20',
    ship_out_time: '2026-08-14T19:00:00',
    ship_in_time: '2026-08-22T12:00:00',
    buyer_id: '星星',
    customer_name: '李女士',
    customer_phone: '13900139000',
    destination: '上海市浦东新区',
  },
  lens_combo: 'lens_400mm',
  accessories: [],
  successor_lens_combo: 'lens_200mm',
  successor_accessories: [],
  can_create: true,
  blocked_reason: null,
}

const mutationResponse = {
  case_id: 7,
  predecessor_rental_id: 101,
  successor_rental_id: 102,
  status: 'pending' as const,
  sf_tracking_number: null,
  tracking: {
    number: null, status: null, summary: null, last_checked_at: null,
  },
  notified_at: null,
  agreed_at: null,
  shipped_at: null,
  completed_at: null,
}

const mountDialog = () => mount(ManualRelayDialog, {
  props: { modelValue: true },
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
})


describe('ManualRelayDialog', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.spyOn(ElMessage, 'success').mockImplementation(() => undefined as never)
    vi.mocked(listManualRelayOptions).mockResolvedValue({
      items: [option], total: 1,
    })
    vi.mocked(createManualRelayCase).mockResolvedValue(mutationResponse)
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('loads devices and previews the automatically matched rental pair', async () => {
    const wrapper = mountDialog()
    await flushPromises()

    wrapper.findComponent(ElSelect).vm.$emit('update:modelValue', 11)
    await nextTick()

    expect(listManualRelayOptions).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).toContain('当前 rental')
    expect(wrapper.text()).toContain('#101 · 王先生')
    expect(wrapper.text()).toContain('已寄回')
    expect(wrapper.text()).toContain('下一笔 rental')
    expect(wrapper.text()).toContain('#102 · 李女士')
    expect(wrapper.get('[data-testid="manual-relay-warning"]').text()).toContain('镜头组合不一致')
  })

  it('creates the relay using only the selected device', async () => {
    const wrapper = mountDialog()
    await flushPromises()
    wrapper.findComponent(ElSelect).vm.$emit('update:modelValue', 11)
    await nextTick()

    await wrapper.get('[data-testid="confirm-manual-relay"]').trigger('click')
    await flushPromises()

    expect(createManualRelayCase).toHaveBeenCalledWith(11)
    expect(ElMessage.success).toHaveBeenCalledWith('接力关系已建立')
    expect(wrapper.emitted('saved')).toEqual([[]])
    expect(wrapper.emitted('update:modelValue')).toEqual([[false]])
  })

  it('shows an empty state when no device has both rentals', async () => {
    vi.mocked(listManualRelayOptions).mockResolvedValueOnce({
      items: [], total: 0,
    })

    const wrapper = mountDialog()
    await flushPromises()

    expect(wrapper.text()).toContain('当前没有同时具备进行中 rental 和下一笔 rental 的设备')
    expect(wrapper.get('[data-testid="confirm-manual-relay"]').attributes('disabled')).toBeDefined()
  })
})
