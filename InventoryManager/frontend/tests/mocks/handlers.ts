import { http, HttpResponse } from 'msw'
import type { Device, Rental } from '@/stores/gantt'

/**
 * MSW Request Handlers
 * 
 * Creates fresh mock data per request to avoid state bleed between tests.
 * Each request handler generates data from factories to ensure isolation.
 */

// Factory functions for creating fresh mock data per request
const createMockDevices = (): Device[] => [
  {
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
  },
  {
    id: 2,
    name: 'Sony A7R',
    serial_number: 'SN002',
    device_model: {
      id: 2,
      name: 'Sony',
      display_name: 'Sony A7R'
    },
    status: 'online',
    is_accessory: false,
    rentals: []
  }
]

const createMockRentals = (): Rental[] => [
  {
    id: 1,
    device_id: 1,
    customer_name: 'Customer A',
    customer_phone: '13800138000',
    destination: 'Beijing',
    start_date: '2026-05-19',
    end_date: '2026-05-26',
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
  },
  {
    id: 2,
    device_id: 2,
    customer_name: 'Customer B',
    customer_phone: '13900139000',
    destination: 'Shanghai',
    start_date: '2026-05-27',
    end_date: '2026-06-02',
    status: 'not_shipped',
    order_amount: 200,
    buyer_id: 'buyer2',
    xianyu_order_no: 'ORDER2',
    ship_out_time: null,
    ship_in_time: null,
    ship_out_tracking_no: null,
    ship_in_tracking_no: null,
    photo_transfer: true,
    bundled_accessories: ['handle'],
    phone_holder_id: 5,
    tripod_id: null,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString()
  }
]

// Shared state for persistence within a test context
// Reset between tests via beforeEach in setup.ts
let mockDevices = createMockDevices()
let mockRentals = createMockRentals()

/**
 * Reset mock data - called by server before each test
 */
export const resetMockData = () => {
  mockDevices = createMockDevices()
  mockRentals = createMockRentals()
}

/**
 * Check if two date ranges overlap
 */
const datesOverlap = (start1: string, end1: string, start2: string, end2: string): boolean => {
  return start1 < end2 && start2 < end1
}

export const handlers = [
  // Gantt data loading endpoint
  http.get('/api/gantt/data', () => {
    return HttpResponse.json({
      success: true,
      data: {
        devices: mockDevices,
        rentals: mockRentals
      }
    })
  }),

  // Get device by ID
  http.get('/api/devices/:id', ({ params }) => {
    const device = mockDevices.find(d => d.id === parseInt(params.id as string))
    if (!device) {
      return HttpResponse.json(
        { success: false, error: 'Device not found' },
        { status: 404 }
      )
    }
    return HttpResponse.json({
      success: true,
      data: device
    })
  }),

  // Create new device
  http.post('/api/devices', async ({ request }) => {
    const data = await request.json() as Partial<Device>
    const newDevice: Device = {
      id: Math.max(...mockDevices.map(d => d.id)) + 1,
      name: data.name || 'Unknown Device',
      serial_number: data.serial_number || `SN${Date.now()}`,
      device_model: data.device_model || { id: 1, name: 'Generic', display_name: 'Generic Device' },
      status: data.status || 'online',
      is_accessory: data.is_accessory || false,
      rentals: []
    }
    mockDevices.push(newDevice)
    return HttpResponse.json({
      success: true,
      data: newDevice
    }, { status: 201 })
  }),

  // Update device status
  http.put('/api/devices/:id', async ({ params, request }) => {
    const device = mockDevices.find(d => d.id === parseInt(params.id as string))
    if (!device) {
      return HttpResponse.json(
        { success: false, error: 'Device not found' },
        { status: 404 }
      )
    }
    const data = await request.json() as Partial<Device>
    Object.assign(device, data)
    return HttpResponse.json({
      success: true,
      data: device
    })
  }),

  // Update device lifecycle
  http.put('/api/devices/:id/lifecycle', async ({ params, request }) => {
    const device = mockDevices.find(d => d.id === parseInt(params.id as string))
    if (!device) {
      return HttpResponse.json(
        { success: false, error: 'Device not found' },
        { status: 404 }
      )
    }
    const data = await request.json() as { lifecycle_status?: string }
    if (data.lifecycle_status) {
      device.status = data.lifecycle_status
    }
    return HttpResponse.json({
      success: true,
      data: device
    })
  }),

  // Get rental by ID - /api/rentals/:id endpoint
  http.get('/api/rentals/:id', ({ params }) => {
    const rental = mockRentals.find(r => r.id === parseInt(params.id as string))
    if (!rental) {
      return HttpResponse.json(
        { success: false, error: 'Rental not found' },
        { status: 404 }
      )
    }
    return HttpResponse.json({
      success: true,
      data: rental
    })
  }),

  // Create rental
  http.post('/api/rentals', async ({ request }) => {
    const data = await request.json() as Partial<Rental>
    const newRental: Rental = {
      id: Math.max(...mockRentals.map(r => r.id)) + 1,
      device_id: data.device_id || 1,
      customer_name: data.customer_name || 'Unknown',
      customer_phone: data.customer_phone || '',
      destination: data.destination || '',
      start_date: data.start_date || new Date().toISOString().split('T')[0],
      end_date: data.end_date || new Date().toISOString().split('T')[0],
      status: data.status || 'not_shipped',
      order_amount: data.order_amount || 0,
      buyer_id: data.buyer_id || '',
      xianyu_order_no: data.xianyu_order_no || '',
      ship_out_time: data.ship_out_time || null,
      ship_in_time: data.ship_in_time || null,
      ship_out_tracking_no: data.ship_out_tracking_no || null,
      ship_in_tracking_no: data.ship_in_tracking_no || null,
      photo_transfer: data.photo_transfer || false,
      bundled_accessories: data.bundled_accessories || [],
      phone_holder_id: data.phone_holder_id || null,
      tripod_id: data.tripod_id || null,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString()
    }
    mockRentals.push(newRental)
    return HttpResponse.json({
      success: true,
      data: newRental
    }, { status: 201 })
  }),

  // Update rental - /web/rentals/:id endpoint
  http.put('/web/rentals/:id', async ({ params, request }) => {
    const rental = mockRentals.find(r => r.id === parseInt(params.id as string))
    if (!rental) {
      return HttpResponse.json(
        { success: false, error: 'Rental not found' },
        { status: 404 }
      )
    }
    const data = await request.json() as Partial<Rental>
    Object.assign(rental, data)
    rental.updated_at = new Date().toISOString()
    return HttpResponse.json({
      success: true,
      data: rental
    })
  }),

  // Update rental - /api/rentals/:id endpoint (alternative)
  http.put('/api/rentals/:id', async ({ params, request }) => {
    const rental = mockRentals.find(r => r.id === parseInt(params.id as string))
    if (!rental) {
      return HttpResponse.json(
        { success: false, error: 'Rental not found' },
        { status: 404 }
      )
    }
    const data = await request.json() as Partial<Rental>
    Object.assign(rental, data)
    rental.updated_at = new Date().toISOString()
    return HttpResponse.json({
      success: true,
      data: rental
    })
  }),

  // Delete rental - /web/rentals/:id endpoint
  http.delete('/web/rentals/:id', ({ params }) => {
    const index = mockRentals.findIndex(r => r.id === parseInt(params.id as string))
    if (index === -1) {
      return HttpResponse.json(
        { success: false, error: 'Rental not found' },
        { status: 404 }
      )
    }
    const deleted = mockRentals.splice(index, 1)[0]
    return HttpResponse.json({
      success: true,
      data: deleted
    })
  }),

  // Find available slot
  http.post('/api/rentals/find-slot', async ({ request }) => {
    const data = await request.json() as { 
      device_id?: number
      start_date?: string
      end_date?: string
    }
    
    // Check if device and dates provided
    if (!data.device_id || !data.start_date || !data.end_date) {
      return HttpResponse.json(
        { success: false, error: 'Missing required fields' },
        { status: 400 }
      )
    }

    // Check for conflicts - only rentals with actual date overlap
    const conflicts = mockRentals.filter(r => 
      r.device_id === data.device_id &&
      r.status !== 'cancelled' &&
      datesOverlap(r.start_date, r.end_date, data.start_date, data.end_date)
    )

    return HttpResponse.json({
      success: true,
      data: {
        available: conflicts.length === 0,
        conflicts: conflicts
      }
    })
  }),

  // Fetch Xianyu order
  http.post('/api/rentals/fetch-xianyu-order', async ({ request }) => {
    const data = await request.json() as { order_no?: string }
    
    if (!data.order_no) {
      return HttpResponse.json(
        { success: false, error: 'Order number required' },
        { status: 400 }
      )
    }

    if (!data.order_no.startsWith('ORDER')) {
      return HttpResponse.json(
        { success: false, error: 'Order not found' },
        { status: 404 }
      )
    }

    return HttpResponse.json({
      success: true,
      data: {
        order_no: data.order_no,
        customer_name: 'Order Customer',
        customer_phone: '13800138000',
        order_amount: 500,
        buyer_id: 'buyer_from_order'
      }
    })
  })
]
