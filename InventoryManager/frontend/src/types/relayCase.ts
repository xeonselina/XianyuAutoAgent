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

export interface RelayDevice {
  id: number | null
  name: string | null
  model: string | null
  model_id: number | null
  model_display_name: string | null
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
  status_text?: string | null
  summary: string | null
  last_checked_at: string | null
  last_update?: string | null
  delivered_time?: string | null
  routes?: RelayTrackingRoute[]
}

export interface RelayTrackingRoute {
  accept_time: string
  accept_address: string
  remark: string
  op_code: string
  first_status_code: string
  first_status_name: string
  secondary_status_code: string
  secondary_status_name: string
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
  source?: 'automatic' | 'manual'
  schedule_changed: boolean
  overlap_days: number
  planned_ship_date: string
  planned_receive_date: string
  predecessor: RelayCustomer
  successor: RelayCustomer
  device: RelayDevice
  lens_combo: string | null
  accessories: RelayAccessory[]
  successor_lens_combo: string | null
  successor_accessories: RelayAccessory[]
  tracking: RelayTracking
  created_at: string | null
  updated_at: string | null
}

export interface ManualRelayRental extends RelayCustomer {
  status: 'not_shipped' | 'scheduled_for_shipping' | 'shipped' | 'returned'
  ship_out_time: string | null
  ship_in_time: string | null
}

export interface ManualRelayOption {
  device: RelayDevice
  predecessor: ManualRelayRental
  successor: ManualRelayRental
  lens_combo: string | null
  accessories: RelayAccessory[]
  successor_lens_combo: string | null
  successor_accessories: RelayAccessory[]
  can_create: boolean
  blocked_reason: string | null
}

export interface ManualRelayOptionsResponse {
  items: ManualRelayOption[]
  total: number
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

export interface RelayCaseListParams {
  statuses: RelayCaseStatus[]
  shipDateFrom: string
  shipDateTo: string
  page: number
  perPage: number
}

export interface RelayCaseMutationResponse {
  case_id: number
  predecessor_rental_id: number
  successor_rental_id: number
  status: RelayCaseStatus
  sf_tracking_number: string | null
  tracking: RelayTracking
  notified_at: string | null
  agreed_at: string | null
  shipped_at: string | null
  completed_at: string | null
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
