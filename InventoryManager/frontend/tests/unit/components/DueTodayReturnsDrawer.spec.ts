import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import DueTodayReturnsDrawer from '@/components/DueTodayReturnsDrawer.vue'
import type { DueTodayRental } from '@/types/dueTodayRental'

const rental: DueTodayRental = {
  id: 12,
  device_model: 'iPhone 15 Pro Max',
  start_date: '2026-07-20',
  end_date: '2026-07-28',
  destination: '浙江省杭州市西湖区测试路 88 号',
  customer_phone: '13900139000',
  status: 'shipped',
}

const mountDrawer = (
  rentals: DueTodayRental[],
  updatingIds = new Set<number>(),
) => mount(DueTodayReturnsDrawer, {
  props: {
    modelValue: true,
    rentals,
    loading: false,
    updatingIds,
  },
  global: {
    stubs: {
      ElDrawer: {
        props: ['modelValue', 'title'],
        template: '<section><h2>{{ title }}</h2><slot /></section>',
      },
      ElButton: {
        props: ['loading', 'disabled'],
        emits: ['click'],
        template: `
          <button
            :disabled="disabled || loading"
            @click="$emit('click')"
          ><slot /></button>
        `,
      },
      ElEmpty: {
        props: ['description'],
        template: '<div class="empty">{{ description }}</div>',
      },
    },
    directives: {
      loading: () => undefined,
    },
  },
})

describe('DueTodayReturnsDrawer', () => {
  it('shows every requested field and emits the row action', async () => {
    const wrapper = mountDrawer([rental])

    expect(wrapper.text()).toContain('iPhone 15 Pro Max')
    expect(wrapper.text()).toContain('2026-07-20 至 2026-07-28')
    expect(wrapper.text()).toContain('浙江省杭州市西湖区测试路 88 号')
    expect(wrapper.text()).toContain('13900139000')
    expect(wrapper.text()).toContain('标记为已寄回')

    await wrapper.get('button').trigger('click')

    expect(wrapper.emitted('mark-returned')).toEqual([[rental.id]])
  })

  it('disables only the row currently being updated', () => {
    const second = { ...rental, id: 13, device_model: 'iPhone 16 Pro' }
    const wrapper = mountDrawer([rental, second], new Set([rental.id]))
    const buttons = wrapper.findAll('button')

    expect(buttons[0].attributes('disabled')).toBeDefined()
    expect(buttons[1].attributes('disabled')).toBeUndefined()
  })

  it('shows a clear empty state', () => {
    const wrapper = mountDrawer([])

    expect(wrapper.text()).toContain('今天暂无应归还订单')
  })
})
