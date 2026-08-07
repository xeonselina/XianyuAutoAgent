import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import RentalInfoCard from '@/components/inspection/RentalInfoCard.vue'
import type { Rental } from '@/types/rental'


const rental = {
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
  accessories: [],
  damage_note: '屏幕右下角碎裂',
} as Rental & { damage_note?: string | null }

const mountCard = (damageNote: string | null) => mount(RentalInfoCard, {
  props: {
    rental: { ...rental, damage_note: damageNote } as Rental,
  },
  global: {
    stubs: {
      ElCard: {
        template: '<section><header><slot name="header" /></header><slot /></section>',
      },
      ElAlert: {
        props: ['title', 'description'],
        template: '<aside class="damage-alert"><strong>{{ title }}</strong><p>{{ description }}</p></aside>',
      },
      ElDescriptions: { template: '<dl><slot /></dl>' },
      ElDescriptionsItem: {
        props: ['label'],
        template: '<div><dt>{{ label }}</dt><dd><slot /></dd></div>',
      },
      ElTag: { template: '<span><slot /></span>' },
      ElEmpty: true,
    },
  },
})

describe('inspection rental damage note', () => {
  it('shows a prominent alert with the complete customer report', () => {
    const wrapper = mountCard('屏幕右下角碎裂')

    expect(wrapper.get('.damage-alert').text()).toContain('用户反馈设备可能损坏')
    expect(wrapper.get('.damage-alert').text()).toContain('屏幕右下角碎裂')
  })

  it('does not show a damage alert when the rental has no report', () => {
    const wrapper = mountCard(null)

    expect(wrapper.find('.damage-alert').exists()).toBe(false)
  })
})

