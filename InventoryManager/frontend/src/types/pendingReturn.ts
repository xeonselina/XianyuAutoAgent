export interface PendingReturn {
  id: number
  warehouse_id: number
  device_model: string
  start_date: string
  end_date: string
  due_date: string
  overdue_days: number
  destination: string | null
  customer_phone: string | null
  status: 'shipped'
}
