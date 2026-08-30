import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import LensComboSelector from '@/components/rental/LensComboSelector.vue'


const stubs = {
  'el-form-item': { template: '<div><slot /></div>' },
  'el-radio-group': { template: '<div><slot /></div>' },
  'el-radio-button': { template: '<button><slot /></button>' },
}

describe('LensComboSelector', () => {
  it('keeps a removed package visible while editing a historical rental', async () => {
    const wrapper = mount(LensComboSelector, {
      props: {
        modelValue: 'pkg_removed',
        modelValueName: '机身 + 旧镜头',
        preserveUnknown: true,
        model: {
          id: 1,
          name: 'camera-pro',
          display_name: '专业相机',
          rental_packages: [{
            id: 'pkg_current',
            name: '机身 + 24-70',
            is_active: true,
            items: [],
          }],
          default_rental_package_id: 'pkg_current',
        },
      },
      global: { stubs },
    })

    expect(wrapper.text()).toContain('机身 + 旧镜头（历史订单）')
    expect(wrapper.text()).toContain('机身 + 24-70')
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
  })
})
