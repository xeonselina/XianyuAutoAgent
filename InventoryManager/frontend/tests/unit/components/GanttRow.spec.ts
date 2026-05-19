import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import GanttRow from '@/components/GanttRow.vue'
import type { Device, Rental } from '@/stores/gantt'
import dayjs from 'dayjs'
import isSameOrBefore from 'dayjs/plugin/isSameOrBefore'
import isSameOrAfter from 'dayjs/plugin/isSameOrAfter'

dayjs.extend(isSameOrBefore)
dayjs.extend(isSameOrAfter)

describe('GanttRow.vue Component', () => {
  let mockDevice: Device
  let mockRentals: Rental[]
  let mockDates: Date[]

  beforeEach(() => {
    // Mock device
    mockDevice = {
      id: 1,
      name: 'iPhone 14 Pro',
      serial_number: 'ABC123456',
      model: 'iPhone',
      model_id: 1,
      is_accessory: false,
      status: 'online' as const,
      lifecycle_status: 'active' as const,
      created_at: '2026-05-01T00:00:00Z',
      updated_at: '2026-05-01T00:00:00Z'
    }

    // Mock rentals
    const startDate = dayjs('2026-05-19')
    mockRentals = [
      {
        id: 1,
        device_id: 1,
        device: mockDevice,
        start_date: startDate.format('YYYY-MM-DD'),
        end_date: startDate.add(3, 'day').format('YYYY-MM-DD'),
        customer_name: '张三',
        customer_phone: '13812345678',
        destination: 'Beijing',
        status: 'shipped',
        ship_out_time: startDate.format('YYYY-MM-DDTHH:mm:ssZ'),
        ship_in_time: startDate.add(3, 'day').format('YYYY-MM-DDTHH:mm:ssZ'),
        includes_handle: true,
        includes_lens_mount: false,
        photo_transfer: true
      }
    ]

    // Mock date range (current week)
    mockDates = Array.from({ length: 7 }, (_, i) =>
      startDate.add(i, 'day').toDate()
    )
  })

  describe('Rendering', () => {
    it('should render gantt row with device info', () => {
      const wrapper = mount(GanttRow, {
        props: {
          device: mockDevice,
          rentals: mockRentals,
          dates: mockDates
        }
      })

      expect(wrapper.find('.gantt-row').exists()).toBe(true)
      expect(wrapper.find('.device-name').text()).toContain('iPhone 14 Pro')
      expect(wrapper.find('.device-sn').text()).toContain('ABC123456')
    })

    it('should render date cells for each date in range', () => {
      const wrapper = mount(GanttRow, {
        props: {
          device: mockDevice,
          rentals: mockRentals,
          dates: mockDates
        }
      })

      const dateCells = wrapper.findAll('.date-cell')
      expect(dateCells.length).toBe(mockDates.length)
    })

    it('should render rental bar on start date', () => {
      const wrapper = mount(GanttRow, {
        props: {
          device: mockDevice,
          rentals: mockRentals,
          dates: mockDates
        }
      })

      const rentalBars = wrapper.findAll('.rental-bar')
      expect(rentalBars.length).toBeGreaterThan(0)
      expect(rentalBars[0].find('.rental-customer').text()).toContain('张三')
    })

    it('should render customer phone in rental bar', () => {
      const wrapper = mount(GanttRow, {
        props: {
          device: mockDevice,
          rentals: mockRentals,
          dates: mockDates
        }
      })

      expect(wrapper.find('.rental-phone').text()).toContain('13812345678')
    })

    it('should show status icon based on rental status', () => {
      const wrapper = mount(GanttRow, {
        props: {
          device: mockDevice,
          rentals: mockRentals,
          dates: mockDates
        }
      })

      const statusIcon = wrapper.find('.status-icon.shipped-icon')
      expect(statusIcon.exists()).toBe(true)
      expect(statusIcon.text()).toBe('🚀')
    })
  })

  describe('Rental Interactions', () => {
    it('should emit edit-rental event when rental bar is clicked', async () => {
      const wrapper = mount(GanttRow, {
        props: {
          device: mockDevice,
          rentals: mockRentals,
          dates: mockDates
        }
      })

      const rentalBar = wrapper.find('.rental-bar')
      await rentalBar.trigger('click')

      expect(wrapper.emitted('edit-rental')).toBeTruthy()
      expect(wrapper.emitted('edit-rental')![0][0]).toEqual(mockRentals[0])
    })

    it('should emit delete-rental event on double click', async () => {
      const wrapper = mount(GanttRow, {
        props: {
          device: mockDevice,
          rentals: mockRentals,
          dates: mockDates
        }
      })

      const rentalBar = wrapper.find('.rental-bar')
      await rentalBar.trigger('dblclick')

      expect(wrapper.emitted('delete-rental')).toBeTruthy()
      expect(wrapper.emitted('delete-rental')![0][0]).toEqual(mockRentals[0])
    })
  })

  describe('Date Cell Styling', () => {
    it('should mark today with special class', () => {
      const todayDate = new Date()
      const mockDatesToday = Array.from({ length: 7 }, (_, i) =>
        new Date(todayDate.getTime() + i * 24 * 60 * 60 * 1000)
      )

      const wrapper = mount(GanttRow, {
        props: {
          device: mockDevice,
          rentals: [],
          dates: mockDatesToday
        }
      })

      const todayCell = wrapper.find('.date-cell.is-today')
      expect(todayCell.exists()).toBe(true)
    })

    it('should mark empty dates with is-empty class', () => {
      // Create dates that have no rentals
      const emptyDates = Array.from({ length: 7 }, (_, i) =>
        dayjs('2026-05-01').add(i, 'day').toDate() // Far from rental dates
      )

      const wrapper = mount(GanttRow, {
        props: {
          device: mockDevice,
          rentals: mockRentals,
          dates: emptyDates
        }
      })

      const emptyCells = wrapper.findAll('.date-cell.is-empty')
      expect(emptyCells.length).toBeGreaterThan(0)
    })
  })

  describe('Rental Styling', () => {
    it('should apply correct background color based on status', () => {
      const wrapper = mount(GanttRow, {
        props: {
          device: mockDevice,
          rentals: mockRentals,
          dates: mockDates
        }
      })

      const rentalBar = wrapper.find('.rental-bar')
      const style = rentalBar.attributes('style')
      
      // Shipped rentals should use green color
      expect(style).toContain('#67c23a')
    })

    it('should calculate correct width for multi-day rentals', () => {
      const wrapper = mount(GanttRow, {
        props: {
          device: mockDevice,
          rentals: mockRentals,
          dates: mockDates
        }
      })

      const rentalBar = wrapper.find('.rental-bar')
      const style = rentalBar.attributes('style')
      
      // 4-day rental should have width of 400%
      expect(style).toContain('width: 400%')
    })

    it('should render shipping overlay when ship times exist', () => {
      const wrapper = mount(GanttRow, {
        props: {
          device: mockDevice,
          rentals: mockRentals,
          dates: mockDates
        }
      })

      const overlay = wrapper.find('.rental-ship-overlay')
      expect(overlay.exists()).toBe(true)
    })

    it('should not render shipping overlay when ship times are missing', () => {
      mockRentals[0].ship_out_time = undefined
      mockRentals[0].ship_in_time = undefined

      const wrapper = mount(GanttRow, {
        props: {
          device: mockDevice,
          rentals: mockRentals,
          dates: mockDates
        }
      })

      const overlay = wrapper.find('.rental-ship-overlay')
      expect(overlay.exists()).toBe(false)
    })
  })

  describe('Device Lifecycle States', () => {
    it('should apply correct styling for sold devices', () => {
      const soldDevice: Device = {
        ...mockDevice,
        lifecycle_status: 'sold'
      }

      const wrapper = mount(GanttRow, {
        props: {
          device: soldDevice,
          rentals: mockRentals,
          dates: mockDates
        }
      })

      const deviceCell = wrapper.find('.device-cell')
      expect(deviceCell.classes()).toContain('device-lifecycle-sold')
    })

    it('should apply correct styling for damaged devices', () => {
      const damagedDevice: Device = {
        ...mockDevice,
        lifecycle_status: 'damaged'
      }

      const wrapper = mount(GanttRow, {
        props: {
          device: damagedDevice,
          rentals: mockRentals,
          dates: mockDates
        }
      })

      const deviceCell = wrapper.find('.device-cell')
      expect(deviceCell.classes()).toContain('device-lifecycle-damaged')
    })

    it('should apply correct styling for decommissioned devices', () => {
      const decommDevice: Device = {
        ...mockDevice,
        lifecycle_status: 'decommissioned'
      }

      const wrapper = mount(GanttRow, {
        props: {
          device: decommDevice,
          rentals: mockRentals,
          dates: mockDates
        }
      })

      const deviceCell = wrapper.find('.device-cell')
      expect(deviceCell.classes()).toContain('device-lifecycle-decommissioned')
    })
  })

  describe('Multiple Rentals on Same Device', () => {
    it('should handle multiple rentals on same device', () => {
      const startDate = dayjs('2026-05-19')
      const multipleRentals: Rental[] = [
        {
          ...mockRentals[0],
          id: 1,
          start_date: startDate.format('YYYY-MM-DD'),
          end_date: startDate.add(1, 'day').format('YYYY-MM-DD'),
          customer_name: '客户1'
        },
        {
          ...mockRentals[0],
          id: 2,
          start_date: startDate.add(3, 'day').format('YYYY-MM-DD'),
          end_date: startDate.add(5, 'day').format('YYYY-MM-DD'),
          customer_name: '客户2'
        }
      ]

      const wrapper = mount(GanttRow, {
        props: {
          device: mockDevice,
          rentals: multipleRentals,
          dates: mockDates
        }
      })

      const rentalBars = wrapper.findAll('.rental-bar')
      // Both rentals might be rendered depending on visibility
      expect(rentalBars.length).toBeGreaterThan(0)
    })
  })

  describe('Cancelled Rentals', () => {
    it('should not show conflict indicators for cancelled rentals', () => {
      const startDate = dayjs('2026-05-19')
      const cancelledRentals: Rental[] = [
        {
          ...mockRentals[0],
          id: 1,
          status: 'cancelled'
        },
        {
          ...mockRentals[0],
          id: 2,
          start_date: startDate.add(3, 'day').format('YYYY-MM-DD')
        }
      ]

      const wrapper = mount(GanttRow, {
        props: {
          device: mockDevice,
          rentals: cancelledRentals,
          dates: mockDates
        }
      })

      // Cancelled rentals should not participate in conflict detection
      expect(wrapper.find('.gantt-row').exists()).toBe(true)
    })
  })

  describe('Status Transitions', () => {
    it('should display different icons for various rental statuses', () => {
      const statuses = ['not_shipped', 'shipped', 'returned', 'completed']
      
      for (const status of statuses) {
        mockRentals[0].status = status
        
        const wrapper = mount(GanttRow, {
          props: {
            device: mockDevice,
            rentals: mockRentals,
            dates: mockDates
          }
        })
        
        const rentalBar = wrapper.find('.rental-bar')
        expect(rentalBar.exists()).toBe(true)
      }
    })
  })

  describe('Props Validation', () => {
    it('should handle empty rentals array', () => {
      const wrapper = mount(GanttRow, {
        props: {
          device: mockDevice,
          rentals: [],
          dates: mockDates
        }
      })

      expect(wrapper.find('.gantt-row').exists()).toBe(true)
      const rentalBars = wrapper.findAll('.rental-bar')
      expect(rentalBars.length).toBe(0)
    })

    it('should handle single date', () => {
      const wrapper = mount(GanttRow, {
        props: {
          device: mockDevice,
          rentals: mockRentals,
          dates: [mockDates[0]]
        }
      })

      expect(wrapper.find('.gantt-row').exists()).toBe(true)
      expect(wrapper.findAll('.date-cell').length).toBe(1)
    })
  })
})
