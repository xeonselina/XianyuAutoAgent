export interface DueTodayRental {
  id: number
  device_model: string
  start_date: string
  end_date: string
  destination: string | null
  customer_phone: string | null
  status: 'shipped'
}
