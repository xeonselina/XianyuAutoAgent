export interface PendingReturn {
  id: number
  warehouse_id: number
  device_model: string
  device_name: string
  customer_name: string
  is_relay_handoff: boolean
  relay_successor_rental_id: number | null
  start_date: string
  end_date: string
  due_date: string
  overdue_days: number
  destination: string | null
  customer_phone: string | null
  status: 'shipped'
}
