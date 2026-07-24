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
}

export interface XianyuOrderAlertSnapshot {
  alerts: XianyuOrderAlert[]
  count: number
  refreshing: boolean
  sync: XianyuOrderAlertSync
}
