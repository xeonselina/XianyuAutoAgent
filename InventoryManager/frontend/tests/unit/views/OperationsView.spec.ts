import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import OperationsView from '@/views/OperationsView.vue'


describe('OperationsView', () => {
  it('groups shipping, inspection, relay, and tracking into one workspace', () => {
    const wrapper = mount(OperationsView, {
      global: {
        stubs: {
          RouterLink: {
            props: ['to'],
            template: '<a :href="to"><slot /></a>',
          },
          ElIcon: { template: '<i><slot /></i>' },
        },
      },
    })

    expect(wrapper.text()).toContain('收货发货')
    expect(wrapper.get('[data-testid="operation-batch-shipping"]').attributes('href')).toBe('/batch-shipping')
    expect(wrapper.get('[data-testid="operation-inspection-records"]').attributes('href')).toBe('/inspection-records')
    expect(wrapper.get('[data-testid="operation-relay-management"]').attributes('href')).toBe('/relay-management')
    expect(wrapper.get('[data-testid="operation-sf-tracking"]').attributes('href')).toBe('/sf-tracking')
  })
})
