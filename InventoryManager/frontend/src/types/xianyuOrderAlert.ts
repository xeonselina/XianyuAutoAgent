export interface XianyuOrderAlert {
  order_no: string
  pay_amount: number
  buyer_nick?: string | null
  receiver_name?: string | null
  receiver_mobile?: string | null
  address?: string | null
  goods_title?: string | null
  goods_sku_text?: string | null
  order_time?: string | null
  first_detected_at?: string | null
  last_seen_at?: string | null
}

export interface XianyuOrderAlertSync {
  last_attempt_at?: string | null
  last_success_at?: string | null
  last_error?: string | null
  snapshot_revision?: number
  sync_status?: 'never' | 'syncing' | 'succeeded' | 'partial_failure' | 'failed' | 'rate_limited'
  current_job_uuid?: string | null
}

export interface XianyuOrderAlertSnapshot {
  alerts: XianyuOrderAlert[]
  count: number
  refreshing: boolean
  sync: XianyuOrderAlertSync
  snapshot_revision?: number
  last_successful_sync_at?: string | null
  sync_status?: XianyuOrderAlertSync['sync_status']
  stale?: boolean
}

export interface XianyuOrderAlertSyncSubmission {
  job_id: string
  snapshot_revision: number
  job_status: string
  reused: boolean
}
