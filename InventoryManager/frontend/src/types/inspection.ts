/**
 * 验货相关类型定义
 */

import type { Rental } from './rental'

/**
 * 检查项类型
 */
export interface CheckItem {
  id?: number
  inspection_record_id?: number
  item_name: string
  is_checked: boolean
  item_order: number
}

/**
 * 验货记录类型
 */
export interface InspectionRecord {
  id: number
  rental_id: number
  device_id: number
  status: 'normal' | 'abnormal'
  inspector_user_id?: number
  inspector_user_uuid?: string
  warehouse_id?: number
  created_at: string
  updated_at: string
  rental?: Rental
  device?: any
  check_items: CheckItem[]
  accessory_reassignments?: AccessoryReassignmentResult[]
}

export interface AccessoryReassignmentResult {
  type_code: string
  display_name: string
  outcome: AccessoryReceiptOutcome
  retained_relay_count: number
  reassigned_count: number
  shortage_count: number
  affected_rental_ids: number[]
  shortage_rental_ids: number[]
}

/**
 * 创建验货记录请求
 */
export interface CreateInspectionRequest {
  rental_id: number
  device_id: number
  warehouse_id: number | null
  check_items: Array<{
    name: string
    is_checked: boolean
    order: number
  }>
  accessory_receipts: Array<{
    accessory_type_id: number
    outcome: AccessoryReceiptOutcome
  }>
}

/**
 * 更新验货记录请求
 */
export interface UpdateInspectionRequest {
  check_items: Array<{
    id: number
    is_checked: boolean
  }>
}

/**
 * 检查清单项（用于动态生成）
 */
export interface ChecklistItem {
  name: string
  order: number
  default_checked?: boolean
}

/**
 * 获取租赁记录响应（包含动态生成的检查清单）
 */
export interface LatestRentalResponse {
  rental: Rental
  checklist: ChecklistItem[]
  accessory_receipts?: LogicalAccessoryReceipt[]
  warehouses?: InspectionWarehouse[]
  selected_warehouse_id?: number | null
}

export type AccessoryReceiptOutcome =
  | 'received_normal'
  | 'received_damaged'
  | 'missing'

export interface LogicalAccessoryReceipt {
  accessory_type_id: number
  type_code: string
  display_name: string
  travels_with_device: boolean
  outcome: AccessoryReceiptOutcome
}

export interface InspectionWarehouse {
  id: number
  name: string
  is_default: boolean
  province: string
  city: string
  district: string
  address_detail: string
}

/**
 * 验货记录列表查询参数
 */
export interface InspectionListParams {
  device_name?: string
  status?: 'normal' | 'abnormal'
  page?: number
  per_page?: number
}

/**
 * 验货记录列表响应
 */
export interface InspectionListResponse {
  records: InspectionRecord[]
  pagination: {
    page: number
    per_page: number
    total: number
    pages: number
    has_prev: boolean
    has_next: boolean
  }
}
