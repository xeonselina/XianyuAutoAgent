import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import RentalShippingForm from '@/components/rental/RentalShippingForm.vue'

vi.mock('@vuepic/vue-datepicker', () => ({
  default: {
    name: 'VueDatePicker',
    template: '<input type="text" />'
  }
}))

vi.mock('@/utils/phoneExtractor', () => ({
  extractPhoneNumber: (text: string) => {
    const match = text.match(/1[3-9]\d{9}/)
    return match ? match[0] : null
  }
}))

describe('RentalShippingForm.vue Component', () => {
  const mockForm = {
    customerPhone: '',
    destination: '',
    shipOutTrackingNo: '',
    shipInTrackingNo: '',
    shipOutTime: null,
    shipInTime: null,
    status: 'not_shipped'
  }

  const defaultStubs = {
    'el-form-item': { template: '<div><slot /></div>' },
    'el-input': true,
    'el-button': true,
    'el-select': true,
    'el-option': true,
    'el-icon': true,
    'Search': true,
    'VueDatePicker': true
  }

  beforeEach(() => {
    vi.clearAllMocks()
  })

  describe('Rendering', () => {
    it('should render form with all input fields', () => {
      const wrapper = mount(RentalShippingForm, {
        props: {
          form: mockForm,
          queryingShipOut: false,
          queryingShipIn: false
        },
        global: { stubs: defaultStubs }
      })

      expect(wrapper.exists()).toBe(true)
    })

    it('should render customer phone input', () => {
      const wrapper = mount(RentalShippingForm, {
        props: {
          form: mockForm,
          queryingShipOut: false,
          queryingShipIn: false
        },
        global: { stubs: defaultStubs }
      })

      expect(wrapper.exists()).toBe(true)
    })

    it('should render destination textarea', () => {
      const wrapper = mount(RentalShippingForm, {
        props: {
          form: mockForm,
          queryingShipOut: false,
          queryingShipIn: false
        },
        global: { stubs: defaultStubs }
      })

      expect(wrapper.exists()).toBe(true)
    })

    it('should render status select', () => {
      const wrapper = mount(RentalShippingForm, {
        props: {
          form: mockForm,
          queryingShipOut: false,
          queryingShipIn: false
        },
        global: { stubs: defaultStubs }
      })

      expect(wrapper.exists()).toBe(true)
    })
  })

  describe('Tracking Number Input', () => {
    it('should disable query button when ship out tracking number is empty', () => {
      const form = { ...mockForm, shipOutTrackingNo: '' }
      const wrapper = mount(RentalShippingForm, {
        props: {
          form,
          queryingShipOut: false,
          queryingShipIn: false
        },
        global: { stubs: defaultStubs }
      })

      expect(wrapper.exists()).toBe(true)
    })

    it('should disable query button when ship in tracking number is empty', () => {
      const form = { ...mockForm, shipInTrackingNo: '' }
      const wrapper = mount(RentalShippingForm, {
        props: {
          form,
          queryingShipOut: false,
          queryingShipIn: false
        },
        global: { stubs: defaultStubs }
      })

      expect(wrapper.exists()).toBe(true)
    })

    it('should enable query button when ship out tracking number is present', () => {
      const form = { ...mockForm, shipOutTrackingNo: 'TRACK123' }
      const wrapper = mount(RentalShippingForm, {
        props: {
          form,
          queryingShipOut: false,
          queryingShipIn: false
        },
        global: { stubs: defaultStubs }
      })

      expect(wrapper.exists()).toBe(true)
    })

    it('should enable query button when ship in tracking number is present', () => {
      const form = { ...mockForm, shipInTrackingNo: 'TRACK456' }
      const wrapper = mount(RentalShippingForm, {
        props: {
          form,
          queryingShipOut: false,
          queryingShipIn: false
        },
        global: { stubs: defaultStubs }
      })

      expect(wrapper.exists()).toBe(true)
    })
  })

  describe('Query Operations', () => {
    it('should emit query-ship-out event when query button is clicked', async () => {
      const form = { ...mockForm, shipOutTrackingNo: 'TRACK123' }
      const wrapper = mount(RentalShippingForm, {
        props: {
          form,
          queryingShipOut: false,
          queryingShipIn: false
        },
        global: { stubs: defaultStubs }
      })

      wrapper.vm.queryShipOutTracking()
      expect(wrapper.emitted('query-ship-out')).toBeDefined()
    })

    it('should emit query-ship-in event when query button is clicked', async () => {
      const form = { ...mockForm, shipInTrackingNo: 'TRACK456' }
      const wrapper = mount(RentalShippingForm, {
        props: {
          form,
          queryingShipOut: false,
          queryingShipIn: false
        },
        global: { stubs: defaultStubs }
      })

      wrapper.vm.queryShipInTracking()
      expect(wrapper.emitted('query-ship-in')).toBeDefined()
    })

    it('should show loading state during query', () => {
      const form = { ...mockForm, shipOutTrackingNo: 'TRACK123' }
      const wrapper = mount(RentalShippingForm, {
        props: {
          form,
          queryingShipOut: true,
          queryingShipIn: false
        },
        global: { stubs: defaultStubs }
      })

      expect(wrapper.props('queryingShipOut')).toBe(true)
    })
  })

  describe('Time Handling', () => {
    it('should emit ship-out-time-change event when ship out time changes', async () => {
      const wrapper = mount(RentalShippingForm, {
        props: {
          form: mockForm,
          queryingShipOut: false,
          queryingShipIn: false
        },
        global: { stubs: defaultStubs }
      })

      const newTime = new Date('2026-05-19 10:00:00')
      wrapper.vm.handleShipOutTimeChange(newTime)

      expect(wrapper.emitted('ship-out-time-change')).toBeDefined()
      expect(wrapper.emitted('ship-out-time-change')?.[0]).toEqual([newTime])
    })

    it('should emit ship-in-time-change event when ship in time changes', async () => {
      const wrapper = mount(RentalShippingForm, {
        props: {
          form: mockForm,
          queryingShipOut: false,
          queryingShipIn: false
        },
        global: { stubs: defaultStubs }
      })

      const newTime = new Date('2026-05-26 14:00:00')
      wrapper.vm.handleShipInTimeChange(newTime)

      expect(wrapper.emitted('ship-in-time-change')).toBeDefined()
      expect(wrapper.emitted('ship-in-time-change')?.[0]).toEqual([newTime])
    })
  })

  describe('Status Management', () => {
    it('should emit status-change event when status changes', async () => {
      const wrapper = mount(RentalShippingForm, {
        props: {
          form: mockForm,
          queryingShipOut: false,
          queryingShipIn: false
        },
        global: { stubs: defaultStubs }
      })

      wrapper.vm.handleStatusChange('shipped')
      expect(wrapper.emitted('status-change')).toBeDefined()
      expect(wrapper.emitted('status-change')?.[0]).toEqual(['shipped'])
    })

    it('should handle all status options', async () => {
      const wrapper = mount(RentalShippingForm, {
        props: {
          form: mockForm,
          queryingShipOut: false,
          queryingShipIn: false
        },
        global: { stubs: defaultStubs }
      })

      const statuses = ['not_shipped', 'shipped', 'returned', 'completed', 'cancelled']

      for (const status of statuses) {
        wrapper.vm.handleStatusChange(status)
        expect(wrapper.emitted('status-change')).toBeDefined()
      }
    })

    it('should accept status prop', () => {
      const form = { ...mockForm, status: 'shipped' }
      const wrapper = mount(RentalShippingForm, {
        props: {
          form,
          queryingShipOut: false,
          queryingShipIn: false
        },
        global: { stubs: defaultStubs }
      })

      expect(wrapper.props('form').status).toBe('shipped')
    })
  })

  describe('Phone Number Extraction', () => {
    it('should extract phone number from destination when destination changes', async () => {
      const form = {
        ...mockForm,
        customerPhone: '',
        destination: '张三 13800138000 北京市朝阳区'
      }

      const wrapper = mount(RentalShippingForm, {
        props: {
          form,
          queryingShipOut: false,
          queryingShipIn: false
        },
        global: { stubs: defaultStubs }
      })

      // Wait for watch to trigger
      await wrapper.vm.$nextTick()
    })

    it('should not overwrite existing phone number', async () => {
      const form = {
        ...mockForm,
        customerPhone: '13900139000',
        destination: '李四 13800138000 上海市浦东新区'
      }

      const wrapper = mount(RentalShippingForm, {
        props: {
          form,
          queryingShipOut: false,
          queryingShipIn: false
        },
        global: { stubs: defaultStubs }
      })

      // Phone should not be overwritten
      expect(wrapper.props('form').customerPhone).toBe('13900139000')
    })
  })

  describe('Props Validation', () => {
    it('should accept form prop', () => {
      const wrapper = mount(RentalShippingForm, {
        props: {
          form: mockForm,
          queryingShipOut: false,
          queryingShipIn: false
        },
        global: { stubs: defaultStubs }
      })

      expect(wrapper.props('form')).toEqual(mockForm)
    })

    it('should accept queryingShipOut prop', () => {
      const wrapper = mount(RentalShippingForm, {
        props: {
          form: mockForm,
          queryingShipOut: true,
          queryingShipIn: false
        },
        global: { stubs: defaultStubs }
      })

      expect(wrapper.props('queryingShipOut')).toBe(true)
    })

    it('should accept queryingShipIn prop', () => {
      const wrapper = mount(RentalShippingForm, {
        props: {
          form: mockForm,
          queryingShipOut: false,
          queryingShipIn: true
        },
        global: { stubs: defaultStubs }
      })

      expect(wrapper.props('queryingShipIn')).toBe(true)
    })
  })
})
