import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useGanttStore, type Device, type Rental } from '@/stores/gantt'
import axios from 'axios'
import dayjs from 'dayjs'

// Mock axios
vi.mock('axios')

describe('Gantt Store Workflow - Integration Tests', () => {
  let pinia: ReturnType<typeof createPinia>
  let store: ReturnType<typeof useGanttStore>

  const createMockDevice = (id: number, name: string, status: string = 'online'): Device => ({
    id,
    name,
    serial_number: `SN${id.toString().padStart(3, '0')}`,
    device_model: {
      id,
      name: name.split(' ')[0],
      display_name: name
    },
    status,
    is_accessory: false,
    rentals: []
  })

  const createMockRental = (
    id: number,
    deviceId: number,
    status: string = 'not_shipped',
    startDate: string = '2026-05-19',
    endDate: string = '2026-05-26'
  ): Rental => ({
    id,
    device_id: deviceId,
    customer_name: `Customer ${id}`,
    customer_phone: '13800138000',
    destination: 'Beijing',
    start_date: startDate,
    end_date: endDate,
    status,
    order_amount: 100 * id,
    buyer_id: `buyer${id}`,
    xianyu_order_no: `ORDER${id}`,
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

  beforeEach(() => {
    pinia = createPinia()
    setActivePinia(pinia)
    store = useGanttStore()
    vi.clearAllMocks()
  })

  afterEach(() => {
    vi.clearAllMocks()
  })

  describe('Device Addition and Rental Association Workflow', () => {
    it('should add device and associate rentals in sequence', () => {
      // Arrange
      const device = createMockDevice(1, 'iPhone 14 Pro')
      const rental1 = createMockRental(1, 1)
      const rental2 = createMockRental(2, 1)

      // Act - Add device first
      store.devices = [device]
      expect(store.devices).toHaveLength(1)

      // Act - Associate rentals
      store.rentals = [rental1, rental2]

      // Assert
      expect(store.rentals).toHaveLength(2)
      const deviceRentals = store.rentals.filter(r => r.device_id === 1)
      expect(deviceRentals).toHaveLength(2)
    })

    it('should handle multiple devices with separate rental pools', () => {
      // Arrange
      const device1 = createMockDevice(1, 'iPhone 14 Pro')
      const device2 = createMockDevice(2, 'Samsung Galaxy')
      const rental1 = createMockRental(1, 1)
      const rental2 = createMockRental(2, 2)

      // Act
      store.devices = [device1, device2]
      store.rentals = [rental1, rental2]

      // Assert
      const device1Rentals = store.rentals.filter(r => r.device_id === 1)
      const device2Rentals = store.rentals.filter(r => r.device_id === 2)
      expect(device1Rentals).toHaveLength(1)
      expect(device2Rentals).toHaveLength(1)
    })

    it('should update device status without affecting rentals', () => {
      // Arrange
      const device = createMockDevice(1, 'iPhone 14 Pro')
      const rental = createMockRental(1, 1)
      store.devices = [device]
      store.rentals = [rental]

      // Act - Transition device status
      store.devices[0].status = 'sold'

      // Assert
      expect(store.devices[0].status).toBe('sold')
      expect(store.rentals[0].device_id).toBe(1)
      expect(store.rentals).toHaveLength(1)
    })
  })

  describe('Rental Status Lifecycle Workflow', () => {
    it('should transition rental through complete booking lifecycle', () => {
      // Arrange
      const device = createMockDevice(1, 'iPhone 14 Pro')
      const rental = createMockRental(1, 1, 'not_shipped')
      store.devices = [device]
      store.rentals = [rental]

      // Act - Progress through lifecycle
      const targetRental = store.rentals[0]
      
      // not_shipped → shipped
      targetRental.status = 'shipped'
      expect(targetRental.status).toBe('shipped')
      
      // shipped → returned
      targetRental.status = 'returned'
      expect(targetRental.status).toBe('returned')
      
      // returned → completed
      targetRental.status = 'completed'
      expect(targetRental.status).toBe('completed')

      // Assert final state
      expect(store.rentals[0].status).toBe('completed')
    })

    it('should handle rental cancellation during any lifecycle phase', () => {
      // Arrange
      const device = createMockDevice(1, 'iPhone 14 Pro')
      const rental1 = createMockRental(1, 1, 'not_shipped')
      const rental2 = createMockRental(2, 1, 'shipped')
      const rental3 = createMockRental(3, 1, 'returned')
      store.devices = [device]
      store.rentals = [rental1, rental2, rental3]

      // Act - Cancel rentals at different lifecycle stages
      store.rentals[0].status = 'cancelled'
      store.rentals[1].status = 'cancelled'
      store.rentals[2].status = 'cancelled'

      // Assert
      expect(store.rentals.every(r => r.status === 'cancelled')).toBe(true)
    })

    it('should track multiple rentals with different statuses', () => {
      // Arrange
      const device = createMockDevice(1, 'iPhone 14 Pro')
      const rentals = [
        createMockRental(1, 1, 'not_shipped'),
        createMockRental(2, 1, 'shipped'),
        createMockRental(3, 1, 'returned'),
        createMockRental(4, 1, 'completed'),
        createMockRental(5, 1, 'cancelled')
      ]
      store.devices = [device]
      store.rentals = rentals

      // Act & Assert - Verify each status is different
      const statusCounts = store.rentals.reduce((acc, r) => {
        acc[r.status] = (acc[r.status] || 0) + 1
        return acc
      }, {} as Record<string, number>)

      expect(statusCounts['not_shipped']).toBe(1)
      expect(statusCounts['shipped']).toBe(1)
      expect(statusCounts['returned']).toBe(1)
      expect(statusCounts['completed']).toBe(1)
      expect(statusCounts['cancelled']).toBe(1)
    })
  })

  describe('Device Lifecycle and Rental Interaction Workflow', () => {
    it('should transition device lifecycle while maintaining active rentals', () => {
      // Arrange
      const device = createMockDevice(1, 'iPhone 14 Pro', 'online')
      const rental1 = createMockRental(1, 1, 'shipped')
      const rental2 = createMockRental(2, 1, 'completed')
      store.devices = [device]
      store.rentals = [rental1, rental2]

      // Act - Device transitions to sold
      const targetDevice = store.devices[0]
      targetDevice.status = 'sold'

      // Assert - Rentals unaffected
      expect(targetDevice.status).toBe('sold')
      expect(store.rentals).toHaveLength(2)
      expect(store.rentals[0].status).toBe('shipped')
      expect(store.rentals[1].status).toBe('completed')
    })

    it('should track device transitions through multiple lifecycle states', () => {
      // Arrange
      const device = createMockDevice(1, 'iPhone 14 Pro', 'online')
      store.devices = [device]

      // Act - Progress through device lifecycle
      const states = ['online', 'damaged', 'decommissioned', 'sold', 'retired']
      let currentState = 'online'

      for (const nextState of states) {
        store.devices[0].status = nextState
        currentState = nextState
        expect(store.devices[0].status).toBe(nextState)
      }

      // Assert final state
      expect(store.devices[0].status).toBe('retired')
    })

    it('should prevent online status from appearing with new rentals when device sold', () => {
      // Arrange
      const device = createMockDevice(1, 'iPhone 14 Pro', 'online')
      const oldRental = createMockRental(1, 1, 'completed')
      store.devices = [device]
      store.rentals = [oldRental]

      // Act - Sell device
      store.devices[0].status = 'sold'

      // Assert - Device is sold, old rental persists
      expect(store.devices[0].status).toBe('sold')
      expect(store.rentals[0].status).toBe('completed')

      // New rentals should be prevented (manually enforce in business logic)
      const isDeviceAvailable = store.devices[0].status === 'online'
      expect(isDeviceAvailable).toBe(false)
    })
  })

  describe('Multi-Step Rental Operations Workflow', () => {
    it('should create rental, update device status, then finalize shipping', () => {
      // Arrange
      const device = createMockDevice(1, 'iPhone 14 Pro')
      store.devices = [device]

      // Act - Step 1: Create rental
      const rental = createMockRental(1, 1, 'not_shipped')
      store.rentals = [rental]
      expect(store.rentals).toHaveLength(1)

      // Act - Step 2: Update rental status to shipped
      store.rentals[0].status = 'shipped'
      expect(store.rentals[0].status).toBe('shipped')

      // Act - Step 3: Add shipping times
      store.rentals[0].ship_out_time = '2026-05-19 09:00:00'
      store.rentals[0].ship_in_time = '2026-05-26 18:00:00'

      // Assert - All steps completed
      const completeRental = store.rentals[0]
      expect(completeRental.status).toBe('shipped')
      expect(completeRental.ship_out_time).toBeDefined()
      expect(completeRental.ship_in_time).toBeDefined()
    })

    it('should add accessories after rental creation', () => {
      // Arrange
      const device = createMockDevice(1, 'iPhone 14 Pro')
      const rental = createMockRental(1, 1)
      store.devices = [device]
      store.rentals = [rental]

      // Act - Add bundled accessories
      store.rentals[0].bundled_accessories = ['handle', 'lens_mount']

      // Act - Add inventory accessories
      store.rentals[0].phone_holder_id = 5
      store.rentals[0].tripod_id = 8

      // Assert
      const updatedRental = store.rentals[0]
      expect(updatedRental.bundled_accessories).toContain('handle')
      expect(updatedRental.bundled_accessories).toContain('lens_mount')
      expect(updatedRental.phone_holder_id).toBe(5)
      expect(updatedRental.tripod_id).toBe(8)
    })

    it('should update rental shipping information in stages', () => {
      // Arrange
      const device = createMockDevice(1, 'iPhone 14 Pro')
      const rental = createMockRental(1, 1, 'shipped')
      store.devices = [device]
      store.rentals = [rental]

      // Act - Stage 1: Set outbound tracking
      store.rentals[0].ship_out_tracking_no = 'SF123456789'
      expect(store.rentals[0].ship_out_tracking_no).toBe('SF123456789')

      // Act - Stage 2: Set outbound time
      store.rentals[0].ship_out_time = '2026-05-19 09:00:00'
      expect(store.rentals[0].ship_out_time).toBe('2026-05-19 09:00:00')

      // Act - Stage 3: Set return tracking
      store.rentals[0].ship_in_tracking_no = 'SF987654321'
      expect(store.rentals[0].ship_in_tracking_no).toBe('SF987654321')

      // Act - Stage 4: Set return time and mark complete
      store.rentals[0].ship_in_time = '2026-05-26 18:00:00'
      store.rentals[0].status = 'completed'

      // Assert
      const completeRental = store.rentals[0]
      expect(completeRental.ship_out_tracking_no).toBe('SF123456789')
      expect(completeRental.ship_in_tracking_no).toBe('SF987654321')
      expect(completeRental.status).toBe('completed')
    })
  })

  describe('Conflict Detection Workflow', () => {
    it('should identify overlapping rental dates on same device', () => {
      // Arrange
      const device = createMockDevice(1, 'iPhone 14 Pro')
      const rental1 = createMockRental(1, 1, 'shipped', '2026-05-19', '2026-05-26')
      const rental2 = createMockRental(2, 1, 'shipped', '2026-05-24', '2026-05-30')
      store.devices = [device]
      store.rentals = [rental1, rental2]

      // Act & Assert - Check for overlap
      const checkOverlap = (r1: Rental, r2: Rental): boolean => {
        const start1 = dayjs(r1.start_date)
        const end1 = dayjs(r1.end_date)
        const start2 = dayjs(r2.start_date)
        const end2 = dayjs(r2.end_date)
        
        return start2.isBefore(end1) && start2.isAfter(start1)
      }

      expect(checkOverlap(rental1, rental2)).toBe(true)
    })

    it('should allow adjacent non-overlapping rentals', () => {
      // Arrange
      const device = createMockDevice(1, 'iPhone 14 Pro')
      const rental1 = createMockRental(1, 1, 'completed', '2026-05-19', '2026-05-26')
      const rental2 = createMockRental(2, 1, 'not_shipped', '2026-05-27', '2026-06-02')
      store.devices = [device]
      store.rentals = [rental1, rental2]

      // Act & Assert
      const checkOverlap = (r1: Rental, r2: Rental): boolean => {
        const start1 = dayjs(r1.start_date)
        const end1 = dayjs(r1.end_date)
        const start2 = dayjs(r2.start_date)
        
        return start2.isBefore(end1) && start2.isAfter(start1)
      }

      expect(checkOverlap(rental1, rental2)).toBe(false)
    })

    it('should detect conflicts across multiple devices', () => {
      // Arrange
      const device1 = createMockDevice(1, 'iPhone 14 Pro')
      const device2 = createMockDevice(2, 'Samsung Galaxy')
      const rental1 = createMockRental(1, 1, 'shipped', '2026-05-19', '2026-05-26')
      const rental2 = createMockRental(2, 2, 'shipped', '2026-05-19', '2026-05-26')
      store.devices = [device1, device2]
      store.rentals = [rental1, rental2]

      // Act - Check for same date conflicts on different devices
      const sameDeviceConflict = store.rentals.filter(r => r.device_id === 1).length > 1
      const device2Rentals = store.rentals.filter(r => r.device_id === 2).length

      // Assert
      expect(sameDeviceConflict).toBe(false)
      expect(device2Rentals).toBe(1)
    })
  })

  describe('Accessory Management Workflow', () => {
    it('should add and remove bundled accessories sequentially', () => {
      // Arrange
      const device = createMockDevice(1, 'iPhone 14 Pro')
      const rental = createMockRental(1, 1)
      store.devices = [device]
      store.rentals = [rental]

      // Act - Add accessories
      store.rentals[0].bundled_accessories = ['handle', 'lens_mount']
      expect(store.rentals[0].bundled_accessories).toHaveLength(2)

      // Act - Remove one
      store.rentals[0].bundled_accessories = store.rentals[0].bundled_accessories.filter(
        a => a !== 'lens_mount'
      )
      
      // Assert
      expect(store.rentals[0].bundled_accessories).toContain('handle')
      expect(store.rentals[0].bundled_accessories).not.toContain('lens_mount')
      expect(store.rentals[0].bundled_accessories).toHaveLength(1)
    })

    it('should manage inventory accessories (phone holder and tripod)', () => {
      // Arrange
      const device = createMockDevice(1, 'iPhone 14 Pro')
      const rental = createMockRental(1, 1)
      store.devices = [device]
      store.rentals = [rental]

      // Act - Assign phone holder
      store.rentals[0].phone_holder_id = 5
      expect(store.rentals[0].phone_holder_id).toBe(5)

      // Act - Assign tripod
      store.rentals[0].tripod_id = 8
      expect(store.rentals[0].tripod_id).toBe(8)

      // Act - Change phone holder
      store.rentals[0].phone_holder_id = 10
      expect(store.rentals[0].phone_holder_id).toBe(10)

      // Act - Remove tripod
      store.rentals[0].tripod_id = null
      expect(store.rentals[0].tripod_id).toBeNull()

      // Assert final state
      expect(store.rentals[0].phone_holder_id).toBe(10)
      expect(store.rentals[0].tripod_id).toBeNull()
    })

    it('should combine bundled and inventory accessories in single workflow', () => {
      // Arrange
      const device = createMockDevice(1, 'iPhone 14 Pro')
      const rental = createMockRental(1, 1)
      store.devices = [device]
      store.rentals = [rental]

      // Act - Add bundled accessories
      store.rentals[0].bundled_accessories = ['handle']

      // Act - Add inventory accessories
      store.rentals[0].phone_holder_id = 5
      store.rentals[0].tripod_id = 8

      // Assert - All accessories present
      const finalRental = store.rentals[0]
      expect(finalRental.bundled_accessories).toContain('handle')
      expect(finalRental.phone_holder_id).toBe(5)
      expect(finalRental.tripod_id).toBe(8)
    })
  })

  describe('Error Handling in Workflows', () => {
    it('should handle invalid device ID gracefully', () => {
      // Arrange
      const device = createMockDevice(1, 'iPhone 14 Pro')
      store.devices = [device]

      // Act - Try to create rental with non-existent device
      const rental = createMockRental(1, 999, 'not_shipped')
      store.rentals = [rental]

      // Assert - Rental created but not associated with device
      const associatedRentals = store.rentals.filter(r => r.device_id === 1)
      expect(associatedRentals).toHaveLength(0)
      expect(store.rentals[0].device_id).toBe(999)
    })

    it('should handle empty store gracefully', () => {
      // Arrange - Empty store
      expect(store.devices).toHaveLength(0)
      expect(store.rentals).toHaveLength(0)

      // Act - Query empty store
      const hasDevices = store.devices.length > 0
      const hasRentals = store.rentals.length > 0

      // Assert
      expect(hasDevices).toBe(false)
      expect(hasRentals).toBe(false)
    })

    it('should handle rapid status changes without data loss', () => {
      // Arrange
      const device = createMockDevice(1, 'iPhone 14 Pro')
      const rental = createMockRental(1, 1, 'not_shipped')
      store.devices = [device]
      store.rentals = [rental]

      // Act - Rapid status changes
      const statusSequence = ['not_shipped', 'shipped', 'returned', 'completed']
      for (const status of statusSequence) {
        store.rentals[0].status = status
      }

      // Assert - Final status correct, no data loss
      expect(store.rentals[0].id).toBe(1)
      expect(store.rentals[0].device_id).toBe(1)
      expect(store.rentals[0].status).toBe('completed')
      expect(store.rentals[0].customer_name).toBe('Customer 1')
    })
  })

  describe('Complex Multi-Step Workflows', () => {
    it('should handle full rental lifecycle with accessories and shipping', () => {
      // Arrange
      const device = createMockDevice(1, 'iPhone 14 Pro')
      store.devices = [device]

      // Act - Step 1: Create rental
      const rental = createMockRental(1, 1, 'not_shipped')
      store.rentals = [rental]

      // Act - Step 2: Add accessories
      store.rentals[0].bundled_accessories = ['handle']
      store.rentals[0].phone_holder_id = 5

      // Act - Step 3: Ship rental
      store.rentals[0].status = 'shipped'
      store.rentals[0].ship_out_time = '2026-05-19 09:00:00'
      store.rentals[0].ship_out_tracking_no = 'SF123456789'

      // Act - Step 4: Rental returns
      store.rentals[0].status = 'returned'
      store.rentals[0].ship_in_time = '2026-05-26 18:00:00'
      store.rentals[0].ship_in_tracking_no = 'SF987654321'

      // Act - Step 5: Complete rental
      store.rentals[0].status = 'completed'

      // Assert - Full workflow complete
      const completed = store.rentals[0]
      expect(completed.status).toBe('completed')
      expect(completed.bundled_accessories).toContain('handle')
      expect(completed.phone_holder_id).toBe(5)
      expect(completed.ship_out_time).toBe('2026-05-19 09:00:00')
      expect(completed.ship_in_time).toBe('2026-05-26 18:00:00')
    })

    it('should manage multiple simultaneous rentals with state isolation', () => {
      // Arrange
      const device = createMockDevice(1, 'iPhone 14 Pro')
      store.devices = [device]

      // Act - Create 3 rentals at different dates
      const rental1 = createMockRental(1, 1, 'completed', '2026-05-01', '2026-05-08')
      const rental2 = createMockRental(2, 1, 'shipped', '2026-05-09', '2026-05-16')
      const rental3 = createMockRental(3, 1, 'not_shipped', '2026-05-17', '2026-05-24')
      store.rentals = [rental1, rental2, rental3]

      // Act - Update each independently
      store.rentals[0].photo_transfer = true
      store.rentals[1].photo_transfer = false
      store.rentals[2].photo_transfer = true

      // Assert - State isolated
      expect(store.rentals[0].photo_transfer).toBe(true)
      expect(store.rentals[1].photo_transfer).toBe(false)
      expect(store.rentals[2].photo_transfer).toBe(true)
      expect(store.rentals.every(r => r.device_id === 1)).toBe(true)
    })
  })
})
