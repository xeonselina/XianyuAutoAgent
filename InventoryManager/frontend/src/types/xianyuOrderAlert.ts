export interface XianyuOrderAlert {
  order_no: string
  xianyu_shop_id: number
  xianyu_shop_name?: string
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
  is_stale?: boolean
  stale_after_seconds?: number
}

export interface XianyuAlertRental {
  id: number
  customer_name: string
  device_name: string
  warehouse_id: number
  warehouse_name: string
  start_date: string
  end_date: string
  status: 'not_shipped' | 'scheduled_for_shipping' | 'shipped'
  parent_rental_id?: number | null
}

export interface XianyuRentalAlert {
  order_no: string
  xianyu_shop_id: number
  xianyu_shop_name: string
  kind: 'closed' | 'refund_review'
  status_text: string
  last_seen_at: string
  rentals: XianyuAlertRental[]
}

export interface XianyuRentalAlertAction {
  orderNo: string
  shopId: number
  rentalId: number
  action: 'delete' | 'review'
}

export interface XianyuRentalAlertIgnore {
  orderNo: string
  shopId: number
  reason: string
}

export interface XianyuOrderAlertSnapshot {
  alerts: XianyuOrderAlert[]
  rental_alerts?: XianyuRentalAlert[]
  count: number
  refreshing: boolean
  sync: XianyuOrderAlertSync
  shops?: { id: number; name: string }[]
}
