import ElementPlus, { ElSteps } from 'element-plus'
import { createPinia, setActivePinia } from 'pinia'
import { mount, flushPromises } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import ScheduleReorderDialog from '@/components/ScheduleReorderDialog.vue'
import { useGanttStore } from '@/stores/gantt'


describe('ScheduleReorderDialog', () => {
  it('显示联系信息并从第二步直接执行', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const store = useGanttStore()
    vi.spyOn(store, 'analyzeScheduleReorder').mockResolvedValue({
      today: '2026-07-11',
      overlaps: [{
        pair_key: '1:2',
        status: 'needs_confirmation',
        binding_id: null,
        overlap_days: 1,
        can_separate: true,
        device: { id: 1, name: 'X300U-03', model_id: 3 },
        predecessor: {
          id: 1,
          customer_name: '王先生',
          customer_phone: '13800138000',
          destination: '北京市朝阳区',
          ship_out_time: '2026-07-12T19:00:00',
          ship_in_time: '2026-07-18T12:00:00',
        },
        successor: {
          id: 2,
          customer_name: '李女士',
          customer_phone: '13900139000',
          destination: '上海市浦东新区',
          ship_out_time: '2026-07-17T19:00:00',
          ship_in_time: '2026-07-23T12:00:00',
        },
      }],
    })
    vi.spyOn(store, 'previewScheduleReorder').mockResolvedValue({
      token: 'signed',
      models: [{
        model_id: 3,
        status: 'OPTIMAL',
        before_devices: 2,
        after_devices: 1,
        movable_rentals: 2,
        changed_rentals: 1,
        total_gap_days: 0,
      }],
      changes: [{
        rental_id: 2,
        model_id: 3,
        customer_name: '李女士',
        customer_phone: '13900139000',
        destination: '上海市浦东新区',
        ship_out_time: '2026-07-17T19:00:00',
        ship_in_time: '2026-07-23T12:00:00',
        from_device_id: 2,
        from_device_name: 'X300U-08',
        to_device_id: 1,
        to_device_name: 'X300U-03',
      }],
      skipped: [],
      overlaps: [],
    })
    vi.spyOn(store, 'executeScheduleReorder').mockResolvedValue({
      changes: [], relay_changes: [],
    })

    const wrapper = mount(ScheduleReorderDialog, {
      props: { modelValue: true },
      global: {
        plugins: [pinia, ElementPlus],
        stubs: {
          ElDialog: {
            props: ['modelValue'],
            template: '<div v-if="modelValue"><slot /><slot name="footer" /></div>',
          },
          ElTable: {
            props: ['data'],
            template: '<div>{{ JSON.stringify(data) }}</div>',
          },
          ElTableColumn: true,
          teleport: true,
          transition: false,
        },
      },
    })
    await flushPromises()

    expect(wrapper.findComponent(ElSteps).props('active')).toBe(0)
    expect(wrapper.text()).toContain('王先生')
    expect(wrapper.text()).toContain('13800138000')
    expect(wrapper.text()).toContain('北京市朝阳区')
    await wrapper.get('[data-test="relay-keep-1-2"]').trigger('click')
    await wrapper.get('[data-test="calculate-preview"]').trigger('click')
    await flushPromises()

    expect(wrapper.findComponent(ElSteps).props('active')).toBe(1)
    expect(wrapper.text()).toContain('最优方案')
    expect(wrapper.text()).not.toContain('OPTIMAL')
    expect(wrapper.text()).toContain('X300U-08')
    expect(wrapper.text()).toContain('X300U-03')
    expect(wrapper.find('[data-test="third-step"]').exists()).toBe(false)
    await wrapper.get('[data-test="execute-reorder"]').trigger('click')
    await flushPromises()
    expect(store.executeScheduleReorder).toHaveBeenCalledWith('signed')
  })

  const statuses = [
    ['OPTIMAL', '最优方案'],
    ['FEASIBLE', '可行方案'],
    ['INFEASIBLE', '无可行方案'],
    ['UNKNOWN', '未得出结果'],
    ['MODEL_INVALID', '求解模型无效'],
    ['NEW_SOLVER_STATUS', '未知状态'],
  ] as const

  it.each(statuses)('将 %s 显示为 %s', async (status, label) => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const store = useGanttStore()
    vi.spyOn(store, 'analyzeScheduleReorder').mockResolvedValue({
      today: '2026-07-12',
      overlaps: [],
    })
    vi.spyOn(store, 'previewScheduleReorder').mockResolvedValue({
      token: 'signed',
      models: [{
        model_id: 3,
        status,
        before_devices: 2,
        after_devices: 1,
        movable_rentals: 2,
        changed_rentals: 1,
        total_gap_days: 0,
      }],
      changes: [],
      skipped: [],
      overlaps: [],
    })

    const wrapper = mount(ScheduleReorderDialog, {
      props: { modelValue: true },
      global: {
        plugins: [pinia, ElementPlus],
        stubs: {
          ElDialog: {
            props: ['modelValue'],
            template: '<div v-if="modelValue"><slot /><slot name="footer" /></div>',
          },
          ElTable: {
            props: ['data'],
            template: '<div>{{ JSON.stringify(data) }}</div>',
          },
          ElTableColumn: true,
          teleport: true,
          transition: false,
        },
      },
    })
    await flushPromises()
    await wrapper.get('[data-test="calculate-preview"]').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain(label)
    expect(wrapper.text()).not.toContain(status)
  })
})
