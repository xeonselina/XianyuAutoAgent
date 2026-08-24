import axios from 'axios'


type ApiEnvelope<T> = {
  success: boolean
  data?: T
  message?: string
}

export type TenantMember = {
  id: number
  phone: string
  role: 'admin' | 'operator'
  status: 'active' | 'disabled'
}

export type SfConfiguration = {
  warehouse_id: number
  partner_id: string | null
  checkword_configured: boolean
  monthly_card_configured: boolean
  test_mode: boolean
  sender_name: string | null
  sender_phone: string | null
  sender_address: string | null
}

export type KuaimaiConfiguration = {
  warehouse_id: number
  app_id: string | null
  app_secret_configured: boolean
  printer_sn: string | null
}

export type WarehouseSettings = {
  id: number
  province: string
  city: string
  name: string
  sf_configured: boolean
  kuaimai_configured: boolean
  sf_config: SfConfiguration | null
  kuaimai_config: KuaimaiConfiguration | null
  created_at: string
  updated_at: string
}

export type WarehouseBaseInput = {
  province: string
  city: string
  name?: string
}

export type SfConfigurationInput = {
  partner_id: string
  checkword: string
  monthly_card: string
  test_mode: boolean
  sender_name: string
  sender_phone: string
  sender_address: string
}

export type KuaimaiConfigurationInput = {
  app_id: string
  app_secret: string
  printer_sn: string
}

const dataFrom = <T>(response: { data: ApiEnvelope<T> }): T => {
  if (!response.data.success || response.data.data === undefined) {
    throw new Error(response.data.message || '请求失败')
  }
  return response.data.data
}

export const listMembers = async () => dataFrom<TenantMember[]>(
  await axios.get('/api/settings/members'),
)

export const createMember = async (
  phone: string,
  role: TenantMember['role'],
) => dataFrom<TenantMember>(
  await axios.post('/api/settings/members', { phone, role }),
)

export const updateMember = async (
  memberId: number,
  patch: Partial<Pick<TenantMember, 'role' | 'status'>>,
) => dataFrom<TenantMember>(
  await axios.patch(`/api/settings/members/${memberId}`, patch),
)

export const listWarehouseSettings = async () => dataFrom<WarehouseSettings[]>(
  await axios.get('/api/settings/warehouses'),
)

export const createWarehouse = async (payload: WarehouseBaseInput) => (
  dataFrom<WarehouseSettings>(await axios.post('/api/settings/warehouses', payload))
)

export const updateWarehouse = async (
  warehouseId: number,
  payload: WarehouseBaseInput,
) => dataFrom<WarehouseSettings>(
  await axios.patch(`/api/settings/warehouses/${warehouseId}`, payload),
)

export const saveSfConfiguration = async (
  warehouseId: number,
  payload: SfConfigurationInput,
) => dataFrom<SfConfiguration>(
  await axios.put(`/api/settings/warehouses/${warehouseId}/sf`, payload),
)

export const saveKuaimaiConfiguration = async (
  warehouseId: number,
  payload: KuaimaiConfigurationInput,
) => dataFrom<KuaimaiConfiguration>(
  await axios.put(`/api/settings/warehouses/${warehouseId}/kuaimai`, payload),
)
