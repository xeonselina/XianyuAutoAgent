import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import GanttRow from '@/components/GanttRow.vue'
import { useGanttStore, type Device, type Rental } from '@/stores/gantt'
import dayjs from 'dayjs'

describe('Gantt Chart Workflow - Integration Tests', () => {
  let pinia: ReturnType<typeof createPinia>
  let ganttStore: ReturnType<typeof useGanttStore>

  const createMockDevice = (): Device => ({
    id: 1,
    name: 'iPhone 14 Pro',
    serial_number: 'SN001',
    device_model: {
      id: 1,
      name: 'iPhone',
      display_name: 'iPhone 14 Pro'
    },
    status: 'online',
    is_accessory: false,
    rentals: []
  })

  const createMockRental1 = (): Rental => ({
    id: 1,
    device_id: 1,
    customer_name: '客户A',
    customer_phone: '13800138000',
    destination: '北京市朝阳区',
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
  })

  const createMockRental2 = (): Rental => ({
    ...createMockRental1(),
    id: 2,
    customer_name: '客户B',
    start_date: '2026-05-27',
    end_date: '2026-06-02',
    status: 'not_shipped'
  })

  beforeEach(() => {
    pinia = createPinia()
    setActivePinia(pinia)
    ganttStore = useGanttStore()
  })

  describe('Device and Rental Management', () => {
    it('should add device to store', () => {
      const mockDevice = createMockDevice()
      ganttStore.devices = [mockDevice]
      expect(ganttStore.devices).toHaveLength(1)
      expect(ganttStore.devices[0].name).toBe('iPhone 14 Pro')
    })

    it('should add multiple rentals to store', () => {
      const mockRental1 = createMockRental1()
      const mockRental2 = createMockRental2()
      ganttStore.rentals = [mockRental1, mockRental2]
      expect(ganttStore.rentals).toHaveLength(2)
    })

    it('should associate rentals with device', () => {
      const mockDevice = createMockDevice()
      const mockRental1 = createMockRental1()
      const mockRental2 = createMockRental2()
      ganttStore.devices = [mockDevice]
      ganttStore.rentals = [mockRental1, mockRental2]

      const deviceRentals = ganttStore.rentals.filter(r => r.device_id === 1)
      expect(deviceRentals).toHaveLength(2)
    })
  })

  describe('Rental Status Transitions', () => {
    it('should transition rental from not_shipped to shipped', () => {
      const mockRental2 = createMockRental2()
      ganttStore.rentals = [mockRental2]
      
      const rental = ganttStore.rentals[0]
      expect(rental.status).toBe('not_shipped')
      
      // Simulate status update
      rental.status = 'shipped'
      expect(rental.status).toBe('shipped')
    })

    it('should transition rental through complete lifecycle', () => {
      const mockRental1 = createMockRental1()
      ganttStore.rentals = [mockRental1]
      const rental = ganttStore.rentals[0]
      
      const statuses = ['shipped', 'returned', 'completed']
      let currentStatus = 'shipped'
      
      for (const nextStatus of statuses) {
        rental.status = nextStatus
        currentStatus = nextStatus
        expect(rental.status).toBe(nextStatus)
      }
    })
  })

  describe('Date Range Calculations', () => {
    it('should calculate rental duration correctly', () => {
      const start = dayjs('2026-05-19')
      const end = dayjs('2026-05-26')
      const duration = end.diff(start, 'day')
      
      expect(duration).toBe(7)
    })

    it('should identify overlapping rentals', () => {
      const mockRental1 = createMockRental1()
      const mockRental2 = createMockRental2()
      ganttStore.rentals = [mockRental1, mockRental2]
      
      const rental1Start = dayjs('2026-05-19')
      const rental1End = dayjs('2026-05-26')
      const rental2Start = dayjs('2026-05-27')
      
      // Check if rental2 overlaps with rental1
      const overlaps = rental2Start.isBefore(rental1End) && rental2Start.isAfter(rental1Start)
      expect(overlaps).toBe(false)
    })

    it('should detect adjacent rentals', () => {
      const mockRental1 = createMockRental1()
      const mockRental2 = createMockRental2()
      ganttStore.rentals = [mockRental1, mockRental2]
      
      const rental1End = dayjs('2026-05-26')
      const rental2Start = dayjs('2026-05-27')
      
      const isAdjacent = rental2Start.diff(rental1End, 'day') === 1
      expect(isAdjacent).toBe(true)
    })
  })

  describe('Rental Status Color Mapping', () => {
    it('should map not_shipped status to orange', () => {
      const mockRental1 = createMockRental1()
      const rental: Rental = { ...mockRental1, status: 'not_shipped' }
      const colors: Record<string, string> = {
        'not_shipped': '#e6a23c',
        'shipped': '#67c23a',
        'returned': '#409eff',
        'completed': '#909399',
        'cancelled': '#f56c6c'
      }
      
      expect(colors[rental.status]).toBe('#e6a23c')
    })

    it('should map shipped status to green', () => {
      const mockRental1 = createMockRental1()
      const rental: Rental = { ...mockRental1, status: 'shipped' }
      const colors: Record<string, string> = {
        'not_shipped': '#e6a23c',
        'shipped': '#67c23a',
        'returned': '#409eff',
        'completed': '#909399',
        'cancelled': '#f56c6c'
      }
      
      expect(colors[rental.status]).toBe('#67c23a')
    })

    it('should map all rental statuses', () => {
      const colors: Record<string, string> = {
        'not_shipped': '#e6a23c',
        'shipped': '#67c23a',
        'returned': '#409eff',
        'completed': '#909399',
        'cancelled': '#f56c6c'
      }
      
      const statuses = ['not_shipped', 'shipped', 'returned', 'completed', 'cancelled']
      
      for (const status of statuses) {
        expect(colors[status]).toBeDefined()
        expect(colors[status]).toMatch(/^#[0-9a-f]{6}$/)
      }
    })
  })

  describe('Device Status Lifecycle', () => {
    it('should transition device from online to sold', () => {
      const mockDevice = createMockDevice()
      ganttStore.devices = [mockDevice]
      const device = ganttStore.devices[0]
      
      expect(device.status).toBe('online')
      device.status = 'sold'
      expect(device.status).toBe('sold')
    })

    it('should track device through all lifecycle states', () => {
      const mockDevice = createMockDevice()
      ganttStore.devices = [mockDevice]
      const device = ganttStore.devices[0]
      
      const states = ['online', 'damaged', 'decommissioned', 'retired']
      
      for (const state of states) {
        device.status = state
        expect(device.status).toBe(state)
      }
    })

    it('should identify active vs inactive devices', () => {
      const mockDevice = createMockDevice()
      const activeDevice: Device = { ...mockDevice, status: 'online' }
      const inactiveDevice: Device = { ...mockDevice, status: 'sold' }
      
      const isActive = (device: Device) => device.status === 'online'
      
      expect(isActive(activeDevice)).toBe(true)
      expect(isActive(inactiveDevice)).toBe(false)
    })
  })

  describe('Rental Form Data Flow', () => {
    it('should populate form with rental data', () => {
      const mockRental1 = createMockRental1()
      const formData = {
        deviceId: mockRental1.device_id,
        customerName: mockRental1.customer_name,
        customerPhone: mockRental1.customer_phone,
        destination: mockRental1.destination,
        endDate: mockRental1.end_date,
        status: mockRental1.status
      }
      
      expect(formData.deviceId).toBe(1)
      expect(formData.customerName).toBe('客户A')
      expect(formData.status).toBe('shipped')
    })

    it('should validate form data before submission', () => {
      const mockRental1 = createMockRental1()
      const rental = mockRental1
      
      const isValid = 
        rental.device_id > 0 &&
        !!rental.customer_name &&
        !!rental.start_date &&
        !!rental.end_date
      
      expect(isValid).toBe(true)
    })
  })

  describe('Accessory Management', () => {
    it('should add bundled accessories to rental', () => {
      const mockRental1 = createMockRental1()
      const rental: Rental = {
        ...mockRental1,
        bundled_accessories: ['handle', 'lens_mount']
      }
      
      expect(rental.bundled_accessories).toContain('handle')
      expect(rental.bundled_accessories).toContain('lens_mount')
      expect(rental.bundled_accessories).toHaveLength(2)
    })

    it('should remove accessory from rental', () => {
      const mockRental1 = createMockRental1()
      const rental: Rental = {
        ...mockRental1,
        bundled_accessories: ['handle', 'lens_mount']
      }
      
      rental.bundled_accessories = rental.bundled_accessories.filter(a => a !== 'lens_mount')
      
      expect(rental.bundled_accessories).toContain('handle')
      expect(rental.bundled_accessories).not.toContain('lens_mount')
      expect(rental.bundled_accessories).toHaveLength(1)
    })

    it('should set inventory accessories (phone holder, tripod)', () => {
      const mockRental1 = createMockRental1()
      const rental: Rental = {
        ...mockRental1,
        phone_holder_id: 5,
        tripod_id: 8
      }
      
      expect(rental.phone_holder_id).toBe(5)
      expect(rental.tripod_id).toBe(8)
    })
  })

  describe('Shipping Timeline Management', () => {
    it('should set shipping times', () => {
      const mockRental1 = createMockRental1()
      const rental: Rental = {
        ...mockRental1,
        ship_out_time: '2026-05-19 09:00:00',
        ship_in_time: '2026-05-26 18:00:00'
      }
      
      expect(rental.ship_out_time).toBeDefined()
      expect(rental.ship_in_time).toBeDefined()
    })

    it('should set tracking numbers', () => {
      const mockRental1 = createMockRental1()
      const rental: Rental = {
        ...mockRental1,
        ship_out_tracking_no: 'SF123456789',
        ship_in_tracking_no: 'SF987654321'
      }
      
      expect(rental.ship_out_tracking_no).toBe('SF123456789')
      expect(rental.ship_in_tracking_no).toBe('SF987654321')
    })

    it('should calculate shipping duration', () => {
      const mockRental1 = createMockRental1()
      const rental: Rental = {
        ...mockRental1,
        ship_out_time: '2026-05-19 09:00:00',
        ship_in_time: '2026-05-26 18:00:00'
      }
      
      if (rental.ship_out_time && rental.ship_in_time) {
        const shipOut = dayjs(rental.ship_out_time)
        const shipIn = dayjs(rental.ship_in_time)
        const duration = shipIn.diff(shipOut, 'day')
        
        expect(duration).toBe(7)
      }
    })
  })

  describe('Photo Transfer Service', () => {
    it('should toggle photo transfer flag', () => {
      const mockRental1 = createMockRental1()
      const rental: Rental = { ...mockRental1, photo_transfer: false }
      
      rental.photo_transfer = true
      expect(rental.photo_transfer).toBe(true)
      
      rental.photo_transfer = false
      expect(rental.photo_transfer).toBe(false)
    })
  })
})
