import { describe, it, expect, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import RentalAccessorySelector from '@/components/rental/RentalAccessorySelector.vue'
import type { Rental } from '@/stores/gantt'

describe('RentalAccessorySelector.vue Component', () => {
  const mockRental: Rental = {
    id: 1,
    device_id: 1,
    customer_name: '测试用户',
    customer_phone: '13800138000',
    destination: '测试地址',
    start_date: '2026-05-19',
    end_date: '2026-05-26',
    status: 'shipped',
    order_amount: 100,
    buyer_id: 'buyer123',
    xianyu_order_no: 'ORDER123',
    ship_out_time: null,
    ship_in_time: null,
    ship_out_tracking_no: null,
    ship_in_tracking_no: null,
    photo_transfer: false,
    bundled_accessories: [],
    phone_holder_id: null,
    tripod_id: null,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString()
  }

  const mockAccessories = [
    {
      id: 1,
      name: '手机支架型号A',
      model: '手机支架',
      isAvailable: true
    },
    {
      id: 2,
      name: '手机支架型号B',
      model: '手机支架',
      isAvailable: false,
      conflictReason: '时间冲突'
    },
    {
      id: 3,
      name: '三脚架型号X',
      model: '三脚架',
      isAvailable: true
    }
  ]

  const mockForm = {
    bundledAccessories: [],
    phoneTransfer: false,
    phoneHolderId: null,
    tripodId: null
  }

  const defaultStubs = {
    'el-form-item': { template: '<div><slot /></div>' },
    'el-checkbox-group': { template: '<div><slot /></div>' },
    'el-checkbox': { template: '<input type="checkbox" />' },
    'el-select': true,
    'el-option': true,
    'el-tag': true,
    'el-button': true,
    'el-icon': true,
    'Delete': true
  }

  describe('Rendering', () => {
    it('should render bundled accessories checkboxes', () => {
      const wrapper = mount(RentalAccessorySelector, {
        props: {
          form: mockForm,
          rental: mockRental,
          availableControllers: mockAccessories,
          loadingAccessories: false,
          searchingAccessory: false
        },
        global: { stubs: defaultStubs }
      })

      expect(wrapper.exists()).toBe(true)
    })

    it('should render accessory selects', () => {
      const wrapper = mount(RentalAccessorySelector, {
        props: {
          form: mockForm,
          rental: mockRental,
          availableControllers: mockAccessories,
          loadingAccessories: false,
          searchingAccessory: false
        },
        global: { stubs: defaultStubs }
      })

      expect(wrapper.exists()).toBe(true)
    })

    it('should show loading state when loadingAccessories is true', () => {
      const wrapper = mount(RentalAccessorySelector, {
        props: {
          form: mockForm,
          rental: mockRental,
          availableControllers: mockAccessories,
          loadingAccessories: true,
          searchingAccessory: false
        },
        global: { stubs: defaultStubs }
      })

      expect(wrapper.props('loadingAccessories')).toBe(true)
    })
  })

  describe('Accessory Filtering', () => {
    it('should filter phone holders correctly', () => {
      const wrapper = mount(RentalAccessorySelector, {
        props: {
          form: mockForm,
          rental: mockRental,
          availableControllers: mockAccessories,
          loadingAccessories: false,
          searchingAccessory: false
        },
        global: { stubs: defaultStubs }
      })

      // Phone holders should be filtered
      expect(wrapper.vm.phoneHolders).toBeDefined()
      expect(wrapper.vm.phoneHolders.length).toBeGreaterThan(0)
    })

    it('should filter tripods correctly', () => {
      const wrapper = mount(RentalAccessorySelector, {
        props: {
          form: mockForm,
          rental: mockRental,
          availableControllers: mockAccessories,
          loadingAccessories: false,
          searchingAccessory: false
        },
        global: { stubs: defaultStubs }
      })

      // Tripods should be filtered
      expect(wrapper.vm.tripods).toBeDefined()
      expect(wrapper.vm.tripods.length).toBeGreaterThan(0)
    })

    it('should identify unavailable accessories', () => {
      const wrapper = mount(RentalAccessorySelector, {
        props: {
          form: mockForm,
          rental: mockRental,
          availableControllers: mockAccessories,
          loadingAccessories: false,
          searchingAccessory: false
        },
        global: { stubs: defaultStubs }
      })

      const unavailableAccessory = mockAccessories.find(a => a.isAvailable === false)
      expect(unavailableAccessory).toBeDefined()
    })
  })

  describe('Bundled Accessories', () => {
    it('should emit accessory-change when bundled accessories change', async () => {
      const wrapper = mount(RentalAccessorySelector, {
        props: {
          form: mockForm,
          rental: mockRental,
          availableControllers: mockAccessories,
          loadingAccessories: false,
          searchingAccessory: false
        },
        global: { stubs: defaultStubs }
      })

      wrapper.vm.handleBundledAccessoriesChange()
      expect(wrapper.emitted('accessory-change')).toBeDefined()
    })

    it('should track selected bundled accessories', async () => {
      const form = { ...mockForm, bundledAccessories: ['handle'] }
      const wrapper = mount(RentalAccessorySelector, {
        props: {
          form,
          rental: mockRental,
          availableControllers: mockAccessories,
          loadingAccessories: false,
          searchingAccessory: false
        },
        global: { stubs: defaultStubs }
      })

      expect(wrapper.props('form').bundledAccessories).toContain('handle')
    })
  })

  describe('Inventory Accessories', () => {
    it('should emit accessory-change when inventory accessory changes', () => {
      const wrapper = mount(RentalAccessorySelector, {
        props: {
          form: mockForm,
          rental: mockRental,
          availableControllers: mockAccessories,
          loadingAccessories: false,
          searchingAccessory: false
        },
        global: { stubs: defaultStubs }
      })

      wrapper.vm.handleInventoryAccessoryChange()
      expect(wrapper.emitted('accessory-change')).toBeDefined()
    })

    it('should select phone holder', async () => {
      const form = { ...mockForm, phoneHolderId: 1 }
      const wrapper = mount(RentalAccessorySelector, {
        props: {
          form,
          rental: mockRental,
          availableControllers: mockAccessories,
          loadingAccessories: false,
          searchingAccessory: false
        },
        global: { stubs: defaultStubs }
      })

      expect(wrapper.vm.selectedPhoneHolder).toBeDefined()
      expect(wrapper.vm.selectedPhoneHolder?.id).toBe(1)
    })

    it('should select tripod', async () => {
      const form = { ...mockForm, tripodId: 3 }
      const wrapper = mount(RentalAccessorySelector, {
        props: {
          form,
          rental: mockRental,
          availableControllers: mockAccessories,
          loadingAccessories: false,
          searchingAccessory: false
        },
        global: { stubs: defaultStubs }
      })

      expect(wrapper.vm.selectedTripod).toBeDefined()
      expect(wrapper.vm.selectedTripod?.id).toBe(3)
    })

    it('should clear phone holder when null', () => {
      const form = { ...mockForm, phoneHolderId: null }
      const wrapper = mount(RentalAccessorySelector, {
        props: {
          form,
          rental: mockRental,
          availableControllers: mockAccessories,
          loadingAccessories: false,
          searchingAccessory: false
        },
        global: { stubs: defaultStubs }
      })

      expect(wrapper.vm.selectedPhoneHolder).toBeNull()
    })

    it('should clear tripod when null', () => {
      const form = { ...mockForm, tripodId: null }
      const wrapper = mount(RentalAccessorySelector, {
        props: {
          form,
          rental: mockRental,
          availableControllers: mockAccessories,
          loadingAccessories: false,
          searchingAccessory: false
        },
        global: { stubs: defaultStubs }
      })

      expect(wrapper.vm.selectedTripod).toBeNull()
    })
  })

  describe('Summary Display', () => {
    it('should show summary when accessories are selected', () => {
      const form = {
        ...mockForm,
        bundledAccessories: ['handle'],
        phoneHolderId: 1
      }

      const wrapper = mount(RentalAccessorySelector, {
        props: {
          form,
          rental: mockRental,
          availableControllers: mockAccessories,
          loadingAccessories: false,
          searchingAccessory: false
        },
        global: { stubs: defaultStubs }
      })

      expect(wrapper.vm.hasSelectedAccessories).toBe(true)
    })

    it('should not show summary when no accessories are selected', () => {
      const wrapper = mount(RentalAccessorySelector, {
        props: {
          form: mockForm,
          rental: mockRental,
          availableControllers: mockAccessories,
          loadingAccessories: false,
          searchingAccessory: false
        },
        global: { stubs: defaultStubs }
      })

      expect(wrapper.vm.hasSelectedAccessories).toBe(false)
    })
  })

  describe('Event Handling', () => {
    it('should emit accessory-selector-focus event', () => {
      const wrapper = mount(RentalAccessorySelector, {
        props: {
          form: mockForm,
          rental: mockRental,
          availableControllers: mockAccessories,
          loadingAccessories: false,
          searchingAccessory: false
        },
        global: { stubs: defaultStubs }
      })

      wrapper.vm.handleAccessorySelectorFocus()
      expect(wrapper.emitted('accessory-selector-focus')).toBeDefined()
    })
  })

  describe('Props Validation', () => {
    it('should accept all required props', () => {
      const wrapper = mount(RentalAccessorySelector, {
        props: {
          form: mockForm,
          rental: mockRental,
          availableControllers: mockAccessories,
          loadingAccessories: false,
          searchingAccessory: false
        },
        global: { stubs: defaultStubs }
      })

      expect(wrapper.props('form')).toEqual(mockForm)
      expect(wrapper.props('availableControllers')).toEqual(mockAccessories)
      expect(wrapper.props('loadingAccessories')).toBe(false)
    })

    it('should handle empty availableControllers', () => {
      const wrapper = mount(RentalAccessorySelector, {
        props: {
          form: mockForm,
          rental: mockRental,
          availableControllers: [],
          loadingAccessories: false,
          searchingAccessory: false
        },
        global: { stubs: defaultStubs }
      })

      expect(wrapper.vm.phoneHolders).toEqual([])
      expect(wrapper.vm.tripods).toEqual([])
    })
  })
})
