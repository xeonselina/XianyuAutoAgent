import axios from 'axios'
import type { LensCombo } from '../config/lensCombo'

export interface CustomerSearchResult {
  customer_name: string
  customer_phone: string
  customer_phone_masked: string
  buyer_id: string
  total_rentals: number
}

export interface CustomerRentalSummary {
  id: number
  device_model_name: string | null
  device_model_display_name: string
  lens_combo: LensCombo | null
  lens_combo_display: string
  order_amount: number | null
  start_date: string | null
  end_date: string | null
  duration_days: number
  customer_name: string | null
  customer_phone: string | null
}

export async function searchCustomers(q: string): Promise<CustomerSearchResult[]> {
  if (!q.trim()) return []
  const { data } = await axios.get('/api/customers/search', { params: { q } })
  if (data?.success) {
    return data.data?.customers ?? []
  }
  return []
}

export async function getCustomerRentals(params: {
  phone?: string
  name?: string
  buyer_id?: string
  limit?: number
}): Promise<CustomerRentalSummary[]> {
  const { data } = await axios.get('/api/customers/rentals', { params: { limit: 5, ...params } })
  if (data?.success) {
    return data.data?.rentals ?? []
  }
  return []
}
