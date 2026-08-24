export interface DefaultWarehouseSetup {
  id: number
  name: string | null
  setup_state: 'pending' | 'ready'
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

export const getDefaultWarehouseSetup = () =>
  request<DefaultWarehouseSetup>('/api/warehouses/setup')

export const setupDefaultWarehouse = (payload: WarehouseProfilePayload) =>
  request<DefaultWarehouseSetup>('/api/warehouses/setup', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })

