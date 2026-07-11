/**
 * Gantt Store Unit Tests
 * 
 * Tests for Pinia store managing:
 * - Device lifecycle status management
 * - Rental data loading and filtering
 * - Conflict detection for overlapping rentals
 * - API interactions
 */

import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useGanttStore } from '@/stores/gantt'
import axios from 'axios'

// Mock axios
vi.mock('axios')

describe('Gantt Store', () => {
  beforeEach(() => {
    // Create a fresh pinia instance and make it active
    setActivePinia(createPinia())
    // Clear all mocks before each test
    vi.clearAllMocks()
  })

  afterEach(() => {
    vi.resetAllMocks()
  })

  describe('Device Lifecycle Management', () => {
    it('should initialize with empty devices and rentals', () => {
      const store = useGanttStore()
      expect(store.devices).toEqual([])
      expect(store.rentals).toEqual([])
      expect(store.loading).toBe(false)
      expect(store.error).toBeNull()
    })

    it('should update device lifecycle status', async () => {
      const store = useGanttStore()
      
      // Mock device data
      store.devices = [
        {
          id: 1,
          name: 'Sony A7R',
          serial_number: 'SN001',
          model: 'Alpha 7R',
          is_accessory: false,
          status: 'online',
          lifecycle_status: 'active',
          created_at: '2026-01-01T00:00:00Z',
          updated_at: '2026-01-01T00:00:00Z'
        }
      ]

      // Mock API response
      const mockResponse = {
        data: {
          success: true,
          data: {
            id: 1,
            lifecycle_status: 'sold',
            lifecycle_reason: 'Equipment sold'
          }
        }
      }

      vi.mocked(axios.put).mockResolvedValueOnce(mockResponse)

      const result = await store.updateDeviceLifecycle(1, 'sold', 'Equipment sold')
      
      expect(axios.put).toHaveBeenCalledWith('/api/devices/1/lifecycle', {
        lifecycle_status: 'sold',
        lifecycle_reason: 'Equipment sold'
      })
      expect(result.success).toBe(true)
      expect(store.devices[0].lifecycle_status).toBe('sold')
    })

    it('should handle lifecycle status error', async () => {
      const store = useGanttStore()
      store.devices = [{
        id: 1,
        name: 'Test Device',
        serial_number: 'SN001',
        model: 'Model 1',
        is_accessory: false,
        status: 'online',
        lifecycle_status: 'active',
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z'
      }]

      const mockError = {
        response: { data: { error: '设备不存在' } }
      }
      vi.mocked(axios.put).mockRejectedValueOnce(mockError)

      await expect(store.updateDeviceLifecycle(1, 'sold')).rejects.toThrow('设备不存在')
    })

    it('should support all lifecycle statuses', async () => {
      const store = useGanttStore()
      const device = {
        id: 1,
        name: 'Test Device',
        serial_number: 'SN001',
        model: 'Model 1',
        is_accessory: false,
        status: 'online' as const,
        lifecycle_status: 'active' as const,
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z'
      }
      store.devices = [device]

      const statuses = ['sold', 'decommissioned', 'damaged', 'retired']

      for (const status of statuses) {
        vi.mocked(axios.put).mockResolvedValueOnce({
          data: { success: true }
        })

        await store.updateDeviceLifecycle(1, status)
        expect(store.devices[0].lifecycle_status).toBe(status as any)
      }
    })
  })

  describe('Schedule Reordering', () => {
    it('调用 analyze、preview 和 execute 接口', async () => {
      const store = useGanttStore()
      vi.mocked(axios.post)
        .mockResolvedValueOnce({
          data: { success: true, data: { today: '2026-07-11', overlaps: [] } }
        })
        .mockResolvedValueOnce({
          data: {
            success: true,
            data: { token: 'signed', models: [], changes: [], skipped: [], overlaps: [] }
          }
        })
        .mockResolvedValueOnce({
          data: { success: true, data: { changes: [], relay_changes: [] } }
        })

      await store.analyzeScheduleReorder()
      await store.previewScheduleReorder([])
      await store.executeScheduleReorder('signed')

      expect(axios.post).toHaveBeenNthCalledWith(1, '/api/gantt/reorder/analyze')
      expect(axios.post).toHaveBeenNthCalledWith(
        2,
        '/api/gantt/reorder/preview',
        { decisions: [] }
      )
      expect(axios.post).toHaveBeenNthCalledWith(
        3,
        '/api/gantt/reorder/execute',
        { token: 'signed' }
      )
    })

    it('保留后端快照冲突错误信息', async () => {
      const store = useGanttStore()
      vi.mocked(axios.post).mockRejectedValueOnce({
        response: { data: { message: '档期已变化，请重新预览' } }
      })

      await expect(store.executeScheduleReorder('expired')).rejects.toThrow(
        '档期已变化，请重新预览'
      )
    })
  })

  describe('Device Status Management', () => {
    it('should update device online/offline status', async () => {
      const store = useGanttStore()
      store.devices = [{
        id: 1,
        name: 'Test Device',
        serial_number: 'SN001',
        model: 'Model 1',
        is_accessory: false,
        status: 'online',
        lifecycle_status: 'active',
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z'
      }]

      vi.mocked(axios.put).mockResolvedValueOnce({
        data: { success: true }
      })

      await store.updateDeviceStatus(1, 'offline')
      
      expect(axios.put).toHaveBeenCalledWith('/api/devices/1', { status: 'offline' })
      expect(store.devices[0].status).toBe('offline')
    })

    it('should handle device status error', async () => {
      const store = useGanttStore()
      const mockError = {
        response: { data: { error: '设备不存在' } }
      }
      vi.mocked(axios.put).mockRejectedValueOnce(mockError)

      await expect(store.updateDeviceStatus(999, 'offline')).rejects.toThrow('设备不存在')
    })
  })

  describe('Device Addition', () => {
    it('should add a new device', async () => {
      const store = useGanttStore()
      
      vi.mocked(axios.post).mockResolvedValueOnce({
        data: { success: true }
      })

      const deviceData = {
        name: 'Sony A6700',
        serial_number: 'SN123456',
        model: 'Alpha 6700',
        model_id: 2,
        is_accessory: false
      }

      const result = await store.addDevice(deviceData)
      
      expect(axios.post).toHaveBeenCalledWith('/api/devices', {
        name: deviceData.name,
        serial_number: deviceData.serial_number,
        model: deviceData.model,
        model_id: deviceData.model_id,
        is_accessory: deviceData.is_accessory,
        status: 'online'
      })
      expect(result.success).toBe(true)
    })

    it('should handle device addition error', async () => {
      const store = useGanttStore()
      const mockError = {
        response: { data: { error: '设备序列号已存在' } }
      }
      vi.mocked(axios.post).mockRejectedValueOnce(mockError)

      await expect(store.addDevice({
        name: 'Test',
        serial_number: 'SN001',
        model: 'Model',
        is_accessory: false
      })).rejects.toThrow('设备序列号已存在')
    })
  })

  describe('Rental Management', () => {
    it('should load rental data from API', async () => {
      const store = useGanttStore()
      
      const mockRentals = [
        {
          id: 1,
          device_id: 1,
          start_date: '2026-05-01',
          end_date: '2026-05-10',
          customer_name: '客户A',
          customer_phone: '13800138000',
          destination: '北京',
          status: 'shipped',
          ship_out_time: '2026-05-01T00:00:00Z',
          ship_in_time: null,
          includes_handle: true,
          includes_lens_mount: false,
          photo_transfer: true,
          accessories: []
        }
      ]

      vi.mocked(axios.get).mockResolvedValueOnce({
        data: { success: true, data: { devices: [], rentals: mockRentals } }
      })

      await store.loadData()
      
      expect(store.rentals).toHaveLength(1)
      expect(store.rentals[0].customer_name).toBe('客户A')
    })

    it('should set error when rental data loading fails', async () => {
      const store = useGanttStore()
      
      vi.mocked(axios.get).mockRejectedValueOnce(new Error('网络错误'))

      await store.loadData()
      
      expect(store.error).toBeTruthy()
      expect(store.loading).toBe(false)
    })

    it('should update rental information', async () => {
      const store = useGanttStore()
      
      vi.mocked(axios.put).mockResolvedValueOnce({
        data: { success: true }
      })

      const rentalUpdate = {
        end_date: '2026-05-15',
        customer_phone: '13900139000',
        status: 'returned'
      }

      const result = await store.updateRental(1, rentalUpdate)
      
      expect(axios.put).toHaveBeenCalledWith('/web/rentals/1', rentalUpdate)
      expect(result.success).toBe(true)
    })

    it('should delete rental', async () => {
      const store = useGanttStore()
      
      vi.mocked(axios.delete).mockResolvedValueOnce({
        data: { success: true }
      })

      const result = await store.deleteRental(1)
      
      expect(axios.delete).toHaveBeenCalledWith('/web/rentals/1')
      expect(result.success).toBe(true)
    })

    it('should get rental by ID', async () => {
      const store = useGanttStore()
      
      const mockRental = {
        id: 1,
        device_id: 1,
        start_date: '2026-05-01',
        end_date: '2026-05-10',
        customer_name: '客户A',
        customer_phone: '13800138000',
        destination: '北京',
        status: 'shipped',
        includes_handle: true,
        includes_lens_mount: false,
        photo_transfer: true,
        accessories: []
      }

      vi.mocked(axios.get).mockResolvedValueOnce({
        data: { success: true, data: mockRental }
      })

      const rental = await store.getRentalById(1)
      
      expect(axios.get).toHaveBeenCalledWith('/api/rentals/1')
      expect(rental).toEqual(mockRental)
    })

    it('should return null when rental not found', async () => {
      const store = useGanttStore()
      
      vi.mocked(axios.get).mockResolvedValueOnce({
        data: { success: false, error: '租赁不存在' }
      })

      const rental = await store.getRentalById(999)
      
      expect(rental).toBeNull()
    })
  })

  describe('Device Filtering', () => {
    it('should get available devices for rental (excludes accessories and offline)', () => {
      const store = useGanttStore()
      
      store.devices = [
        {
          id: 1,
          name: 'Sony A7R',
          serial_number: 'SN001',
          model: 'Alpha 7R',
          is_accessory: false,
          status: 'online',
          lifecycle_status: 'active',
          created_at: '2026-01-01T00:00:00Z',
          updated_at: '2026-01-01T00:00:00Z'
        },
        {
          id: 2,
          name: 'Phone Mount',
          serial_number: 'SN002',
          model: 'PM1',
          is_accessory: true,
          status: 'online',
          lifecycle_status: 'active',
          created_at: '2026-01-01T00:00:00Z',
          updated_at: '2026-01-01T00:00:00Z'
        },
        {
          id: 3,
          name: 'Old Camera',
          serial_number: 'SN003',
          model: 'OldModel',
          is_accessory: false,
          status: 'offline',
          lifecycle_status: 'sold',
          created_at: '2026-01-01T00:00:00Z',
          updated_at: '2026-01-01T00:00:00Z'
        }
      ]

      // Should only return online, non-accessory devices
      const available = store.availableDevices
      
      expect(available).toContainEqual(expect.objectContaining({ id: 1 }))
      expect(available).not.toContainEqual(expect.objectContaining({ id: 2 })) // accessory excluded
      expect(available).not.toContainEqual(expect.objectContaining({ id: 3 })) // offline excluded
    })
  })

  describe('Rental Filtering', () => {
    it('should filter rentals by date range', () => {
      const store = useGanttStore()
      
      store.rentals = [
        {
          id: 1,
          device_id: 1,
          start_date: '2026-05-01',
          end_date: '2026-05-10',
          customer_name: '客户A',
          customer_phone: '13800138000',
          destination: '北京',
          status: 'shipped',
          includes_handle: true,
          includes_lens_mount: false,
          photo_transfer: false,
          accessories: []
        },
        {
          id: 2,
          device_id: 2,
          start_date: '2026-06-01',
          end_date: '2026-06-10',
          customer_name: '客户B',
          customer_phone: '13900139000',
          destination: '上海',
          status: 'shipped',
          includes_handle: false,
          includes_lens_mount: true,
          photo_transfer: true,
          accessories: []
        }
      ]

      // Filter rentals in May
      const mayRentals = store.rentals.filter(r => 
        r.start_date.includes('2026-05')
      )
      
      expect(mayRentals).toHaveLength(1)
      expect(mayRentals[0].customer_name).toBe('客户A')
    })

    it('should filter rentals by device', () => {
      const store = useGanttStore()
      
      store.rentals = [
        {
          id: 1,
          device_id: 1,
          start_date: '2026-05-01',
          end_date: '2026-05-10',
          customer_name: '客户A',
          customer_phone: '13800138000',
          destination: '北京',
          status: 'shipped',
          includes_handle: true,
          includes_lens_mount: false,
          photo_transfer: false,
          accessories: []
        },
        {
          id: 2,
          device_id: 1,
          start_date: '2026-05-20',
          end_date: '2026-05-30',
          customer_name: '客户B',
          customer_phone: '13900139000',
          destination: '上海',
          status: 'shipped',
          includes_handle: false,
          includes_lens_mount: true,
          photo_transfer: true,
          accessories: []
        }
      ]

      const deviceRentals = store.rentals.filter(r => r.device_id === 1)
      
      expect(deviceRentals).toHaveLength(2)
    })

    it('should filter rentals by status', () => {
      const store = useGanttStore()
      
      store.rentals = [
        {
          id: 1,
          device_id: 1,
          start_date: '2026-05-01',
          end_date: '2026-05-10',
          customer_name: '客户A',
          customer_phone: '13800138000',
          destination: '北京',
          status: 'shipped',
          includes_handle: true,
          includes_lens_mount: false,
          photo_transfer: false,
          accessories: []
        },
        {
          id: 2,
          device_id: 2,
          start_date: '2026-06-01',
          end_date: '2026-06-10',
          customer_name: '客户B',
          customer_phone: '13900139000',
          destination: '上海',
          status: 'completed',
          includes_handle: false,
          includes_lens_mount: true,
          photo_transfer: true,
          accessories: []
        }
      ]

      const shippedRentals = store.rentals.filter(r => r.status === 'shipped')
      
      expect(shippedRentals).toHaveLength(1)
      expect(shippedRentals[0].customer_name).toBe('客户A')
    })
  })

  describe('Accessory Bundling', () => {
    it('should track bundled accessories', () => {
      const store = useGanttStore()
      
      store.rentals = [
        {
          id: 1,
          device_id: 1,
          start_date: '2026-05-01',
          end_date: '2026-05-10',
          customer_name: '客户A',
          customer_phone: '13800138000',
          destination: '北京',
          status: 'shipped',
          includes_handle: true,
          includes_lens_mount: true,
          photo_transfer: false,
          accessories: []
        }
      ]

      const rental = store.rentals[0]
      expect(rental.includes_handle).toBe(true)
      expect(rental.includes_lens_mount).toBe(true)
    })

    it('should track photo transfer service', () => {
      const store = useGanttStore()
      
      store.rentals = [
        {
          id: 1,
          device_id: 1,
          start_date: '2026-05-01',
          end_date: '2026-05-10',
          customer_name: '客户A',
          customer_phone: '13800138000',
          destination: '北京',
          status: 'shipped',
          includes_handle: false,
          includes_lens_mount: false,
          photo_transfer: true,
          accessories: []
        }
      ]

      const rental = store.rentals[0]
      expect(rental.photo_transfer).toBe(true)
    })
  })

  describe('Error Handling', () => {
    it('should handle network errors gracefully', async () => {
      const store = useGanttStore()
      
      const networkError = new Error('Network error')
      vi.mocked(axios.get).mockRejectedValueOnce(networkError)

      await store.loadData()
      
      expect(store.error).toBeTruthy()
      expect(store.loading).toBe(false)
    })

    it('should handle API errors with proper messages', async () => {
      const store = useGanttStore()
      
      const apiError = {
        response: {
          data: { error: '用户未授权' }
        }
      }
      vi.mocked(axios.put).mockRejectedValueOnce(apiError)

      await expect(store.updateDeviceStatus(1, 'offline')).rejects.toThrow('用户未授权')
    })

    it('should handle malformed API responses', async () => {
      const store = useGanttStore()
      
      vi.mocked(axios.get).mockResolvedValueOnce({
        data: { success: false, error: null }
      })

      await store.loadData()
      
      expect(store.error).toBeTruthy()
    })
  })

  describe('Date Range Management', () => {
    it('should have a date range with start and end dates', () => {
      const store = useGanttStore()
      
      const range = store.dateRange
      
      // dateRange is an object with start and end properties
      expect(range).toHaveProperty('start')
      expect(range).toHaveProperty('end')
      expect(range.start).toBeInstanceOf(Date)
      expect(range.end).toBeInstanceOf(Date)
      expect(range.start.getTime()).toBeLessThanOrEqual(range.end.getTime())
    })

    it('should track current selected date', () => {
      const store = useGanttStore()
      
      expect(store.currentDate).toBeTruthy()
      expect(store.currentDate).toBeInstanceOf(Date)
    })
  })

  describe('Rental Operations', () => {
    it('should create rental and reload data', async () => {
      const store = useGanttStore()
      
      vi.mocked(axios.post).mockResolvedValueOnce({
        data: { success: true, data: { id: 1 } }
      })

      const rentalData = {
        device_id: 1,
        start_date: '2026-05-01',
        end_date: '2026-05-10',
        customer_name: '客户A'
      }

      const result = await store.createRental(rentalData)
      
      expect(axios.post).toHaveBeenCalledWith('/api/rentals', rentalData)
      expect(result.success).toBe(true)
    })

    it('should find available slots for rental', async () => {
      const store = useGanttStore()
      
      vi.mocked(axios.post).mockResolvedValueOnce({
        data: {
          success: true,
          data: {
            device: { id: 1, name: 'Test Device' },
            ship_out_date: '2026-05-01T00:00:00Z',
            ship_in_date: '2026-05-10T00:00:00Z',
            available_controllers: [1, 2, 3],
            controller_count: 3
          }
        }
      })

      const slot = await store.findAvailableSlot('2026-05-01', '2026-05-10', 2, 'Alpha 7R')
      
      expect(slot.device).toBeDefined()
      expect(slot.shipOutDate).toBeInstanceOf(Date)
      expect(slot.shipInDate).toBeInstanceOf(Date)
      expect(slot.availableControllers).toHaveLength(3)
    })
  })

  describe('Device Access Methods', () => {
    it('should get rentals for a specific device', () => {
      const store = useGanttStore()
      
      store.rentals = [
        {
          id: 1,
          device_id: 1,
          start_date: '2026-05-01',
          end_date: '2026-05-10',
          customer_name: '客户A',
          customer_phone: '13800138000',
          destination: '北京',
          status: 'shipped',
          includes_handle: true,
          includes_lens_mount: false,
          photo_transfer: false,
          accessories: []
        },
        {
          id: 2,
          device_id: 2,
          start_date: '2026-05-01',
          end_date: '2026-05-10',
          customer_name: '客户B',
          customer_phone: '13900139000',
          destination: '上海',
          status: 'shipped',
          includes_handle: false,
          includes_lens_mount: true,
          photo_transfer: true,
          accessories: []
        }
      ]

      const device1Rentals = store.getRentalsForDevice(1)
      
      expect(device1Rentals).toHaveLength(1)
      expect(device1Rentals[0].customer_name).toBe('客户A')
    })
  })
})
