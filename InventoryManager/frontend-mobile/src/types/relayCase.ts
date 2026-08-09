export type RelayCaseStatus =
  | 'pending'
  | 'notified'
  | 'agreed'
  | 'shipped'
  | 'completed'

export interface RelayCustomer {
  id: number
  start_date: string
  end_date: string
  buyer_id: string | null
  customer_name: string | null
  customer_phone: string | null
  destination: string | null
}

export interface RelayAccessory {
  id?: number
  name: string
  type?: string | null
  is_bundled?: boolean
}

export interface RelayTracking {
  number: string | null
  status: string | null
  summary: string | null
  last_checked_at: string | null
}

export interface RelayXianyuSync {
  attempted: boolean
  success: boolean
  message: string
}

export interface RelayCase {
  case_id: number | null
  pair_key: string
  status: RelayCaseStatus
  binding_id: number | null
  schedule_changed: boolean
  overlap_days: number
  planned_ship_date: string
  planned_receive_date: string
  device: {
    id: number | null
    name: string | null
    model: string | null
    model_id: number | null
    model_display_name: string | null
  }
  lens_combo: string | null
  accessories: RelayAccessory[]
  successor_lens_combo: string | null
  successor_accessories: RelayAccessory[]
  predecessor: RelayCustomer
  successor: RelayCustomer
  tracking: RelayTracking
  created_at: string | null
  updated_at: string | null
}

export interface RelayCaseListResponse {
  items: RelayCase[]
  total: number
  page: number
  per_page: number
  pages: number
  open_total: number
  filters: {
    statuses: RelayCaseStatus[]
    ship_date_from: string
    ship_date_to: string
  }
}

export interface RelayCaseMutationResponse {
  case_id: number
  predecessor_rental_id: number
  successor_rental_id: number
  status: RelayCaseStatus
  sf_tracking_number: string | null
  tracking: RelayTracking
  xianyu_sync?: RelayXianyuSync
}

export interface RelayTrackingBatchResponse {
  items: Array<{
    case_id: number
    success: boolean
    tracking?: RelayTracking
    message?: string
  }>
  total: number
  success_count: number
}
