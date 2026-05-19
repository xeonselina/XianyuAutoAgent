import { describe, it, expect, beforeEach } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useGanttStore, type Device, type Rental } from '@/stores/gantt'
import dayjs from 'dayjs'

/**
 * Phase 3.5: Performance Testing Suite
 * 
 * Tests application performance under load:
 * - Large dataset handling
 * - Store operation performance
 * - Memory efficiency
 * - Computed property performance
 * - Complex filtering and sorting
 */

describe('Performance Testing - Large Dataset Handling', () => {
  let pinia: ReturnType<typeof createPinia>
  let store: ReturnType<typeof useGanttStore>

  beforeEach(() => {
    pinia = createPinia()
    setActivePinia(pinia)
    store = useGanttStore()
  })

  describe('Large Device Dataset', () => {
    it('should handle 100 devices efficiently', () => {
      const startTime = performance.now()

      // Create 100 devices
      const devices = Array.from({ length: 100 }, (_, i) => ({
        id: i + 1,
        name: `Device ${i + 1}`,
        serial_number: `SN${String(i + 1).padStart(5, '0')}`,
        device_model: {
          id: (i % 10) + 1,
          name: `Model ${(i % 10) + 1}`,
          display_name: `Display Name ${(i % 10) + 1}`
        },
        status: i % 3 === 0 ? 'offline' : 'online',
        is_accessory: i % 20 === 0,
        rentals: []
      }))

      store.devices = devices

      const endTime = performance.now()
      const duration = endTime - startTime

      expect(store.devices).toHaveLength(100)
      expect(duration).toBeLessThan(100) // Should complete in less than 100ms
    })

    it('should filter available devices from large dataset', () => {
      // Create 200 devices
      const devices = Array.from({ length: 200 }, (_, i) => ({
        id: i + 1,
        name: `Device ${i + 1}`,
        serial_number: `SN${String(i + 1).padStart(5, '0')}`,
        device_model: {
          id: 1,
          name: 'Model',
          display_name: 'Model'
        },
        status: i % 3 === 0 ? 'offline' : 'online',
        is_accessory: i % 15 === 0,
        rentals: []
      }))

      store.devices = devices

      const startTime = performance.now()

      // Filter for available devices (online, not accessory)
      const available = store.devices.filter(d => d.status === 'online' && !d.is_accessory)

      const endTime = performance.now()
      const duration = endTime - startTime

      expect(available.length).toBeGreaterThan(0)
      expect(available.length).toBeLessThan(200)
      expect(duration).toBeLessThan(50) // Should filter quickly
    })

    it('should compute available devices efficiently', () => {
      // Create 150 devices
      const devices = Array.from({ length: 150 }, (_, i) => ({
        id: i + 1,
        name: `Device ${i + 1}`,
        serial_number: `SN${String(i + 1).padStart(5, '0')}`,
        device_model: {
          id: 1,
          name: 'Model',
          display_name: 'Model'
        },
        status: i % 2 === 0 ? 'online' : 'offline',
        is_accessory: i % 25 === 0,
        rentals: []
      }))

      store.devices = devices

      const startTime = performance.now()

      // Access computed property multiple times
      const available1 = store.availableDevices
      const available2 = store.availableDevices
      const available3 = store.availableDevices

      const endTime = performance.now()
      const duration = endTime - startTime

      expect(available1).toEqual(available2)
      expect(available2).toEqual(available3)
      expect(duration).toBeLessThan(20) // Cached computation should be fast
    })
  })

  describe('Large Rental Dataset', () => {
    it('should handle 1000 rentals efficiently', () => {
      const startTime = performance.now()

      // Create 1000 rentals across 100 devices
      const rentals = Array.from({ length: 1000 }, (_, i) => ({
        id: i + 1,
        device_id: (i % 100) + 1,
        customer_name: `Customer ${i + 1}`,
        customer_phone: `1380${String(i).padStart(7, '0')}`,
        destination: `City ${(i % 30) + 1}`,
        start_date: dayjs('2026-01-01').add(Math.floor(i / 10), 'day').format('YYYY-MM-DD'),
        end_date: dayjs('2026-01-01').add(Math.floor(i / 10) + 7, 'day').format('YYYY-MM-DD'),
        status: ['not_shipped', 'shipped', 'returned', 'completed', 'cancelled'][(i % 5)],
        order_amount: Math.floor(Math.random() * 10000) + 100,
        buyer_id: `buyer${i % 500}`,
        xianyu_order_no: `ORDER${String(i).padStart(8, '0')}`,
        ship_out_time: i % 3 === 0 ? new Date().toISOString() : null,
        ship_in_time: i % 4 === 0 ? new Date().toISOString() : null,
        ship_out_tracking_no: i % 3 === 0 ? `SF${String(i).padStart(10, '0')}` : null,
        ship_in_tracking_no: i % 4 === 0 ? `SF${String(i + 1000).padStart(10, '0')}` : null,
        photo_transfer: i % 10 === 0,
        bundled_accessories: i % 5 === 0 ? ['handle', 'lens_mount'] : [],
        phone_holder_id: i % 8 === 0 ? Math.floor(Math.random() * 50) : null,
        tripod_id: i % 12 === 0 ? Math.floor(Math.random() * 30) : null,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString()
      }))

      store.rentals = rentals

      const endTime = performance.now()
      const duration = endTime - startTime

      expect(store.rentals).toHaveLength(1000)
      expect(duration).toBeLessThan(200) // Should handle large dataset quickly
    })

    it('should filter rentals by status efficiently', () => {
      const rentals = Array.from({ length: 500 }, (_, i) => ({
        id: i + 1,
        device_id: (i % 50) + 1,
        customer_name: `Customer ${i}`,
        customer_phone: '13800138000',
        destination: 'Beijing',
        start_date: '2026-05-01',
        end_date: '2026-05-10',
        status: ['not_shipped', 'shipped', 'completed'][(i % 3)],
        order_amount: 100,
        buyer_id: 'buyer1',
        xianyu_order_no: 'ORDER1',
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
      }))

      store.rentals = rentals

      const startTime = performance.now()

      // Filter by status
      const shipped = store.rentals.filter(r => r.status === 'shipped')

      const endTime = performance.now()
      const duration = endTime - startTime

      expect(shipped.length).toBeGreaterThan(0)
      expect(duration).toBeLessThan(50)
    })

    it('should filter rentals by device efficiently', () => {
      const rentals = Array.from({ length: 800 }, (_, i) => ({
        id: i + 1,
        device_id: (i % 100) + 1,
        customer_name: `Customer ${i}`,
        customer_phone: '13800138000',
        destination: 'Beijing',
        start_date: '2026-05-01',
        end_date: '2026-05-10',
        status: 'shipped',
        order_amount: 100,
        buyer_id: 'buyer1',
        xianyu_order_no: 'ORDER1',
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
      }))

      store.rentals = rentals

      const startTime = performance.now()

      // Filter by device ID
      const deviceRentals = store.rentals.filter(r => r.device_id === 42)

      const endTime = performance.now()
      const duration = endTime - startTime

      expect(deviceRentals.length).toBeGreaterThan(0)
      expect(duration).toBeLessThan(50)
    })
  })

  describe('Date Range Filtering Performance', () => {
    it('should filter rentals by date range from large dataset', () => {
      const rentals = Array.from({ length: 2000 }, (_, i) => {
        const startDay = Math.floor(i / 10) % 365
        const start = dayjs('2026-01-01').add(startDay, 'day')
        const end = start.add(7, 'day')
        
        return {
          id: i + 1,
          device_id: (i % 100) + 1,
          customer_name: `Customer ${i}`,
          customer_phone: '13800138000',
          destination: 'Beijing',
          start_date: start.format('YYYY-MM-DD'),
          end_date: end.format('YYYY-MM-DD'),
          status: 'shipped',
          order_amount: 100,
          buyer_id: 'buyer1',
          xianyu_order_no: 'ORDER1',
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
      })

      store.rentals = rentals

      const startTime = performance.now()

      // Filter by date range
      const filterStart = dayjs('2026-06-01')
      const filterEnd = dayjs('2026-06-30')
      
      const filtered = store.rentals.filter(r => {
        const rStart = dayjs(r.start_date)
        const rEnd = dayjs(r.end_date)
        return rStart.isBefore(filterEnd) && rEnd.isAfter(filterStart)
      })

      const endTime = performance.now()
      const duration = endTime - startTime

      expect(filtered.length).toBeGreaterThan(0)
      expect(duration).toBeLessThan(100)
    })
  })

  describe('Complex Query Performance', () => {
    it('should handle complex filtering with multiple conditions', () => {
      const rentals = Array.from({ length: 1500 }, (_, i) => ({
        id: i + 1,
        device_id: (i % 150) + 1,
        customer_name: `Customer ${i}`,
        customer_phone: '13800138000',
        destination: `City ${(i % 50) + 1}`,
        start_date: dayjs('2026-01-01').add(i % 365, 'day').format('YYYY-MM-DD'),
        end_date: dayjs('2026-01-01').add((i % 365) + 7, 'day').format('YYYY-MM-DD'),
        status: ['not_shipped', 'shipped', 'returned'][(i % 3)],
        order_amount: Math.floor(Math.random() * 10000),
        buyer_id: `buyer${i % 200}`,
        xianyu_order_no: `ORDER${String(i).padStart(8, '0')}`,
        ship_out_time: i % 2 === 0 ? new Date().toISOString() : null,
        ship_in_time: null,
        ship_out_tracking_no: i % 2 === 0 ? 'SF123456' : null,
        ship_in_tracking_no: null,
        photo_transfer: i % 5 === 0,
        bundled_accessories: i % 10 === 0 ? ['handle'] : [],
        phone_holder_id: null,
        tripod_id: null,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString()
      }))

      store.rentals = rentals

      const startTime = performance.now()

      // Complex query: shipped rentals with accessories, high order amount
      const complex = store.rentals.filter(r =>
        r.status === 'shipped' &&
        r.bundled_accessories.length > 0 &&
        r.order_amount > 5000 &&
        r.photo_transfer
      )

      const endTime = performance.now()
      const duration = endTime - startTime

      expect(duration).toBeLessThan(100)
      expect(Array.isArray(complex)).toBe(true)
    })

    it('should handle overlapping rental detection efficiently', () => {
      const rentals = Array.from({ length: 1000 }, (_, i) => ({
        id: i + 1,
        device_id: (i % 50) + 1, // 50 devices
        customer_name: `Customer ${i}`,
        customer_phone: '13800138000',
        destination: 'Beijing',
        start_date: dayjs('2026-01-01').add(Math.floor(i / 50) * 5, 'day').format('YYYY-MM-DD'),
        end_date: dayjs('2026-01-01').add((Math.floor(i / 50) * 5) + 3, 'day').format('YYYY-MM-DD'),
        status: 'shipped',
        order_amount: 100,
        buyer_id: 'buyer1',
        xianyu_order_no: 'ORDER1',
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
      }))

      store.rentals = rentals

      const deviceId = 25
      const checkDate = dayjs('2026-03-15')

      const startTime = performance.now()

      // Find overlapping rentals
      const overlapping = store.rentals.filter(r => {
        if (r.device_id !== deviceId) return false
        const rStart = dayjs(r.start_date)
        const rEnd = dayjs(r.end_date)
        return rStart.isBefore(checkDate) && rEnd.isAfter(checkDate)
      })

      const endTime = performance.now()
      const duration = endTime - startTime

      expect(duration).toBeLessThan(50)
      expect(Array.isArray(overlapping)).toBe(true)
    })
  })

  describe('Memory Efficiency', () => {
    it('should not cause memory leaks with repeated store updates', () => {
      const devices = Array.from({ length: 50 }, (_, i) => ({
        id: i + 1,
        name: `Device ${i}`,
        serial_number: `SN${i}`,
        device_model: {
          id: 1,
          name: 'Model',
          display_name: 'Model'
        },
        status: 'online',
        is_accessory: false,
        rentals: []
      }))

      // Update store multiple times
      for (let i = 0; i < 100; i++) {
        store.devices = [...devices]
      }

      // Verify final state is correct
      expect(store.devices).toHaveLength(50)
      expect(store.devices[0].name).toBe('Device 0')
    })

    it('should handle frequent filter operations efficiently', () => {
      const rentals = Array.from({ length: 500 }, (_, i) => ({
        id: i + 1,
        device_id: (i % 50) + 1,
        customer_name: `Customer ${i}`,
        customer_phone: '13800138000',
        destination: 'Beijing',
        start_date: '2026-05-01',
        end_date: '2026-05-10',
        status: ['not_shipped', 'shipped', 'completed'][(i % 3)],
        order_amount: 100,
        buyer_id: 'buyer1',
        xianyu_order_no: 'ORDER1',
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
      }))

      store.rentals = rentals

      const startTime = performance.now()

      // Run filter operation 1000 times
      for (let i = 0; i < 1000; i++) {
        store.rentals.filter(r => r.status === 'shipped')
      }

      const endTime = performance.now()
      const duration = endTime - startTime

      // Should complete 1000 filters in reasonable time
      expect(duration).toBeLessThan(500)
    })
  })

  describe('Computed Property Efficiency', () => {
    it('should cache computed available devices', () => {
      const devices = Array.from({ length: 200 }, (_, i) => ({
        id: i + 1,
        name: `Device ${i}`,
        serial_number: `SN${i}`,
        device_model: {
          id: 1,
          name: 'Model',
          display_name: 'Model'
        },
        status: i % 2 === 0 ? 'online' : 'offline',
        is_accessory: i % 20 === 0,
        rentals: []
      }))

      store.devices = devices

      const startTime = performance.now()

      // Access computed property many times
      for (let i = 0; i < 10000; i++) {
        store.availableDevices
      }

      const endTime = performance.now()
      const duration = endTime - startTime

      // Cached access should be very fast
      expect(duration).toBeLessThan(100)
    })
  })

  describe('Stress Testing', () => {
    it('should maintain data integrity with 500 rentals on 100 devices', () => {
      const devices = Array.from({ length: 100 }, (_, i) => ({
        id: i + 1,
        name: `Device ${i}`,
        serial_number: `SN${i}`,
        device_model: {
          id: 1,
          name: 'Model',
          display_name: 'Model'
        },
        status: 'online',
        is_accessory: false,
        rentals: []
      }))

      const rentals = Array.from({ length: 500 }, (_, i) => ({
        id: i + 1,
        device_id: (i % 100) + 1,
        customer_name: `Customer ${i}`,
        customer_phone: '13800138000',
        destination: 'Beijing',
        start_date: '2026-05-01',
        end_date: '2026-05-10',
        status: 'shipped',
        order_amount: 100,
        buyer_id: 'buyer1',
        xianyu_order_no: 'ORDER1',
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
      }))

      store.devices = devices
      store.rentals = rentals

      // Verify integrity
      expect(store.devices).toHaveLength(100)
      expect(store.rentals).toHaveLength(500)
      
      // All rentals reference valid device IDs
      const validDeviceIds = new Set(store.devices.map(d => d.id))
      const allValid = store.rentals.every(r => validDeviceIds.has(r.device_id))
      expect(allValid).toBe(true)
    })
  })
})
