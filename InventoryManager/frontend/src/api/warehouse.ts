export interface WarehouseSummary {
  id: number
  warehouse_uuid: string
  name: string | null
  status: 'active' | 'inactive'
  setup_state: 'pending' | 'ready'
  is_default: boolean
  contact_name: string | null
  contact_phone: string | null
  province: string | null
  city: string | null
  district: string | null
  address_detail: string | null
}

export interface WarehouseProfilePayload {
  name: string
  contact_name: string
  contact_phone: string
  province: string
  city: string
  district: string
  address_detail: string
}

export type WarehousePreferenceScene = 'booking' | 'shipping' | 'inspection'
export type WarehousePreferences = Partial<Record<WarehousePreferenceScene, number>>

export interface WarehouseDevice {
  id: number
  name: string
  serial_number: string | null
  model: string | null
  model_id?: number | null
  warehouse_id: number | null
  lifecycle_status?: string
}

export interface WarehouseDeviceModel {
  id: number
  name: string
  display_name: string
}

export interface DeviceMovePreview {
  device: { id: number; name: string; warehouse_id: number | null }
  current_warehouse: Pick<WarehouseSummary, 'id' | 'name' | 'status' | 'setup_state'> | null
  target_warehouse: Pick<WarehouseSummary, 'id' | 'name' | 'status' | 'setup_state'>
  is_same_warehouse: boolean
  affected_rental_ids: number[]
  affected_rentals: Array<{
    rental_id: number
    order_number: string | null
    customer_start_date: string
    customer_end_date: string
    logistics_days: number | null
    planned_ship_out_date: string | null
    planned_return_date: string | null
    affected_accessory_types: Array<{
      accessory_type_id: number
      name: string
    }>
  }>
  revision: string
  preserves_logistics_facts: boolean
}

export interface DeviceMoveResult {
  device_id: number
  from_warehouse_id: number | null
  to_warehouse_id: number
  movement_id: string
  affected_rental_ids: number[]
  accessory_fulfillment: Array<{
    rental_id: number
    accessory_type_id: number
    accessory_name: string
    status: 'fulfilled' | 'shortage'
  }>
}

interface ApiEnvelope<T> {
  success: boolean
  data?: T
  message?: string
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init)
  const body = await response.json() as ApiEnvelope<T>
  if (!response.ok || !body.success || body.data === undefined) {
    throw new Error(body.message || '仓库操作失败')
  }
  return body.data
}

export const listWarehouses = () =>
  request<WarehouseSummary[]>('/api/warehouses')

export const listWarehouseDevices = () =>
  request<WarehouseDevice[]>('/api/warehouses/devices')

export const listWarehouseDeviceModels = () =>
  request<WarehouseDeviceModel[]>('/api/warehouses/device-models')

export const createWarehouseMainDevice = (payload: {
  name: string
  serial_number: string
  model_id: number
  warehouse_id?: number
}) => request<WarehouseDevice>('/api/warehouses/devices', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(payload),
})

export const getDefaultWarehouseSetup = () =>
  request<WarehouseSummary>('/api/warehouses/setup')

export const setupDefaultWarehouse = (payload: WarehouseProfilePayload) =>
  request<WarehouseSummary>('/api/warehouses/setup', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })

export const createWarehouse = (payload: WarehouseProfilePayload) =>
  request<WarehouseSummary>('/api/warehouses', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(payload),
})

export const updateWarehouse = (
  warehouseId: number,
  payload: WarehouseProfilePayload,
) => request<WarehouseSummary>(`/api/warehouses/${warehouseId}`, {
  method: 'PUT',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(payload),
})

export const setDefaultWarehouse = (warehouseId: number) =>
  request<WarehouseSummary>(`/api/warehouses/${warehouseId}/default`, {
    method: 'POST',
  })

export const deactivateWarehouse = (warehouseId: number) =>
  request<WarehouseSummary>(`/api/warehouses/${warehouseId}/deactivate`, {
    method: 'POST',
  })

export const getWarehousePreferences = () =>
  request<WarehousePreferences>('/api/warehouses/preferences')

export const setWarehousePreference = (
  scene: WarehousePreferenceScene,
  warehouseId: number,
) => request<{ scene: WarehousePreferenceScene; warehouse_id: number }>(
  `/api/warehouses/preferences/${scene}`,
  {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ warehouse_id: warehouseId }),
  },
)

export const previewDeviceMove = (payload: {
  device_id: number
  target_warehouse_id: number
}) => request<DeviceMovePreview>('/api/warehouses/device-moves/preview', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(payload),
})

export const confirmDeviceMove = (payload: {
  device_id: number
  target_warehouse_id: number
  expected_current_warehouse_id: number | null
  expected_preview_revision: string
  confirmed: true
  note?: string
}) => request<DeviceMoveResult>('/api/warehouses/device-moves/confirm', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(payload),
})
