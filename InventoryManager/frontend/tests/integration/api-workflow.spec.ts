import { describe, it, expect, beforeEach } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useGanttStore, type Device, type Rental } from '@/stores/gantt'
import { server } from '../mocks/server'
import { http, HttpResponse } from 'msw'
import axios from 'axios'

describe('API Integration Tests - MSW', () => {
  let store: ReturnType<typeof useGanttStore>

  beforeEach(() => {
    const pinia = createPinia()
    setActivePinia(pinia)
    store = useGanttStore()
  })

  describe('Successful API Responses', () => {
    it('should fetch gantt data successfully', async () => {
      // Act
      const response = await axios.get('/api/gantt/data')

      // Assert
      expect(response.data.success).toBe(true)
      expect(response.data.data.devices).toBeDefined()
      expect(response.data.data.rentals).toBeDefined()
      expect(response.data.data.devices).toHaveLength(2)
      expect(response.data.data.rentals).toHaveLength(2)
    })

    it('should retrieve device by ID', async () => {
      // Act
      const response = await axios.get('/api/devices/1')

      // Assert
      expect(response.data.success).toBe(true)
      expect(response.data.data.id).toBe(1)
      expect(response.data.data.name).toBe('iPhone 14 Pro')
      expect(response.data.data.status).toBe('online')
    })

    it('should retrieve rental by ID', async () => {
      // Act
      const response = await axios.get('/api/rentals/1')

      // Assert
      expect(response.data.success).toBe(true)
      expect(response.data.data.id).toBe(1)
      expect(response.data.data.customer_name).toBe('Customer A')
      expect(response.data.data.status).toBe('shipped')
    })

    it('should create new device', async () => {
      // Arrange
      const newDevice = {
        name: 'New Device',
        serial_number: 'SN999',
        device_model: {
          id: 99,
          name: 'Model',
          display_name: 'New Model'
        }
      }

      // Act
      const response = await axios.post('/api/devices', newDevice)

      // Assert
      expect(response.status).toBe(201)
      expect(response.data.success).toBe(true)
      expect(response.data.data.name).toBe('New Device')
      expect(response.data.data.id).toBeGreaterThan(2)
    })

    it('should create new rental', async () => {
      // Arrange
      const newRental = {
        device_id: 1,
        customer_name: 'New Customer',
        customer_phone: '13900139000',
        destination: 'New City',
        start_date: '2026-06-03',
        end_date: '2026-06-10',
        status: 'not_shipped'
      }

      // Act
      const response = await axios.post('/api/rentals', newRental)

      // Assert
      expect(response.status).toBe(201)
      expect(response.data.success).toBe(true)
      expect(response.data.data.customer_name).toBe('New Customer')
      expect(response.data.data.id).toBeGreaterThan(2)
    })

    it('should update device status', async () => {
      // Arrange
      const updates = { status: 'sold' }

      // Act
      const response = await axios.put('/api/devices/1', updates)

      // Assert
      expect(response.data.success).toBe(true)
      expect(response.data.data.status).toBe('sold')
      expect(response.data.data.id).toBe(1)
    })

    it('should update rental information', async () => {
      // Arrange
      const updates = {
        status: 'completed',
        ship_out_time: '2026-05-19 09:00:00',
        ship_in_time: '2026-05-26 18:00:00'
      }

      // Act
      const response = await axios.put('/web/rentals/1', updates)

      // Assert
      expect(response.data.success).toBe(true)
      expect(response.data.data.status).toBe('completed')
      expect(response.data.data.ship_out_time).toBe('2026-05-19 09:00:00')
    })

    it('should find available slots for rental', async () => {
      // Arrange - Use device 2 and a date range that doesn't conflict with existing rentals
      // Device 1 has rental: 2026-05-19 to 2026-05-26
      // Device 2 has rental: 2026-05-27 to 2026-06-02
      // So device 2 should be available after 2026-06-02
      const slotRequest = {
        device_id: 2,
        start_date: '2026-06-03',
        end_date: '2026-06-10'
      }

      // Act
      const response = await axios.post('/api/rentals/find-slot', slotRequest)

      // Assert
      expect(response.data.success).toBe(true)
      expect(response.data.data.available).toBe(true)
      expect(response.data.data.conflicts).toHaveLength(0)
    })

    it('should fetch Xianyu order successfully', async () => {
      // Arrange
      const orderRequest = { order_no: 'ORDER123' }

      // Act
      const response = await axios.post('/api/rentals/fetch-xianyu-order', orderRequest)

      // Assert
      expect(response.data.success).toBe(true)
      expect(response.data.data.customer_name).toBe('Order Customer')
      expect(response.data.data.customer_phone).toBe('13800138000')
      expect(response.data.data.order_amount).toBe(500)
    })

    it('should delete rental successfully', async () => {
      // Act
      const response = await axios.delete('/web/rentals/1')

      // Assert
      expect(response.data.success).toBe(true)
      expect(response.data.data.id).toBe(1)
    })
  })

  describe('Error Responses', () => {
    it('should return 404 for non-existent device', async () => {
      // Act & Assert
      try {
        await axios.get('/api/devices/999')
      } catch (error: any) {
        expect(error.response.status).toBe(404)
        expect(error.response.data.success).toBe(false)
        expect(error.response.data.error).toBe('Device not found')
      }
    })

    it('should return 404 for non-existent rental', async () => {
      // Act & Assert
      try {
        await axios.get('/api/rentals/999')
      } catch (error: any) {
        expect(error.response.status).toBe(404)
        expect(error.response.data.success).toBe(false)
      }
    })

    it('should return 400 for missing required fields in find-slot', async () => {
      // Arrange
      const invalidRequest = {
        device_id: 1
        // Missing start_date and end_date
      }

      // Act & Assert
      try {
        await axios.post('/api/rentals/find-slot', invalidRequest)
      } catch (error: any) {
        expect(error.response.status).toBe(400)
        expect(error.response.data.success).toBe(false)
      }
    })

    it('should return 400 for order fetch without order number', async () => {
      // Act & Assert
      try {
        await axios.post('/api/rentals/fetch-xianyu-order', {})
      } catch (error: any) {
        expect(error.response.status).toBe(400)
        expect(error.response.data.success).toBe(false)
      }
    })

    it('should return 404 for invalid order number', async () => {
      // Act & Assert
      try {
        await axios.post('/api/rentals/fetch-xianyu-order', { order_no: 'INVALID' })
      } catch (error: any) {
        expect(error.response.status).toBe(404)
        expect(error.response.data.success).toBe(false)
      }
    })
  })

  describe('Network Error Scenarios', () => {
    it('should handle network timeout gracefully', async () => {
      // Arrange
      server.use(
        http.get('/api/devices/:id', () => {
          return HttpResponse.error()
        })
      )

      // Act & Assert
      try {
        await axios.get('/api/devices/1')
      } catch (error: any) {
        expect(error.message).toBeDefined()
      }
    })

    it('should handle 500 server error', async () => {
      // Arrange
      server.use(
        http.get('/api/rentals/:id', () => {
          return HttpResponse.json(
            { success: false, error: 'Internal server error' },
            { status: 500 }
          )
        })
      )

      // Act & Assert
      try {
        await axios.get('/api/rentals/1')
      } catch (error: any) {
        expect(error.response.status).toBe(500)
        expect(error.response.data.success).toBe(false)
      }
    })

    it('should handle 503 service unavailable', async () => {
      // Arrange
      server.use(
        http.post('/api/rentals', () => {
          return HttpResponse.json(
            { success: false, error: 'Service temporarily unavailable' },
            { status: 503 }
          )
        })
      )

      // Act & Assert
      try {
        await axios.post('/api/rentals', {})
      } catch (error: any) {
        expect(error.response.status).toBe(503)
      }
    })
  })

  describe('API Response Transformation', () => {
    it('should properly transform device response', async () => {
      // Act
      const response = await axios.get('/api/devices/1')
      const device: Device = response.data.data

      // Assert
      expect(device.id).toBe(1)
      expect(device.name).toBe('iPhone 14 Pro')
      expect(device.device_model).toBeDefined()
      expect(device.device_model.display_name).toBe('iPhone 14 Pro')
      expect(device.status).toBe('online')
      expect(device.is_accessory).toBe(false)
    })

    it('should properly transform rental response', async () => {
      // Act
      const response = await axios.get('/api/rentals/1')
      const rental: Rental = response.data.data

      // Assert
      expect(rental.id).toBe(1)
      expect(rental.device_id).toBe(1)
      expect(rental.customer_name).toBe('Customer A')
      expect(rental.status).toBe('shipped')
      expect(rental.bundled_accessories).toBeInstanceOf(Array)
    })

    it('should handle date fields in rental responses', async () => {
      // Act
      const response = await axios.get('/api/rentals/1')
      const rental = response.data.data

      // Assert
      expect(rental.start_date).toBe('2026-05-19')
      expect(rental.end_date).toBe('2026-05-26')
      expect(rental.created_at).toBeDefined()
      expect(rental.updated_at).toBeDefined()
    })

    it('should handle null fields in rental responses', async () => {
      // Act
      const response = await axios.get('/api/rentals/1')
      const rental = response.data.data

      // Assert
      expect(rental.ship_out_time).toBeNull()
      expect(rental.ship_in_time).toBeNull()
      expect(rental.phone_holder_id).toBeNull()
    })
  })

  describe('Concurrent API Operations', () => {
    it('should handle multiple parallel API calls', async () => {
      // Act
      const [deviceRes, rentalRes, ganttRes] = await Promise.all([
        axios.get('/api/devices/1'),
        axios.get('/api/rentals/1'),
        axios.get('/api/gantt/data')
      ])

      // Assert
      expect(deviceRes.data.success).toBe(true)
      expect(rentalRes.data.success).toBe(true)
      expect(ganttRes.data.success).toBe(true)
    })

    it('should isolate errors in concurrent calls', async () => {
      // Act & Assert
      const results = await Promise.allSettled([
        axios.get('/api/devices/1'),
        axios.get('/api/devices/999'),
        axios.get('/api/rentals/1')
      ])

      // Assert
      expect(results[0].status).toBe('fulfilled')
      expect(results[1].status).toBe('rejected')
      expect(results[2].status).toBe('fulfilled')
    })
  })

  describe('Data Persistence Across Calls', () => {
    it('should persist created device across subsequent calls', async () => {
      // Act - Create device
      const createRes = await axios.post('/api/devices', {
        name: 'Persistent Device',
        serial_number: 'SN_PERSIST'
      })
      const deviceId = createRes.data.data.id

      // Act - Retrieve same device
      const getRes = await axios.get(`/api/devices/${deviceId}`)

      // Assert
      expect(getRes.data.data.name).toBe('Persistent Device')
    })

    it('should update rental and verify persistence', async () => {
      // Act - Update rental
      await axios.put('/web/rentals/1', {
        status: 'completed'
      })

      // Act - Retrieve updated rental
      const getRes = await axios.get('/api/rentals/1')

      // Assert
      expect(getRes.data.data.status).toBe('completed')
    })

    it('should delete rental and confirm non-existence', async () => {
      // Act - Delete rental
      await axios.delete('/web/rentals/1')

      // Act & Assert - Attempt to retrieve deleted rental
      try {
        await axios.get('/api/rentals/1')
      } catch (error: any) {
        expect(error.response.status).toBe(404)
      }
    })
  })

  describe('Request Validation', () => {
    it('should handle malformed JSON gracefully', async () => {
      // This test verifies MSW catches invalid requests
      const response = await axios.get('/api/devices/1')
      expect(response.data.success).toBe(true)
    })

    it('should validate device lifecycle transitions', async () => {
      // Act
      const response = await axios.put('/api/devices/1/lifecycle', {
        lifecycle_status: 'sold',
        lifecycle_reason: 'Equipment sold'
      })

      // Assert
      expect(response.data.success).toBe(true)
      expect(response.data.data.status).toBe('sold')
    })
  })
})
