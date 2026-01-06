/**
 * 租赁相关类型定义
 */

/**
 * 附件选择数据（UI层）
 */
export interface AccessorySelection {
  // 配套附件（手柄、镜头支架）- 使用字符串数组表示选中的附件类型
  bundled_accessories: ('handle' | 'lens_mount')[]
  // 库存附件 - 使用设备ID
  phone_holder_id: number | null
  tripod_id: number | null
}

/**
 * 租赁表单数据（UI层）
 */
export interface RentalFormData {
  device_id: number
  start_date: string
  end_date: string
  customer_name: string
  customer_phone?: string
  destination?: string
  xianyu_order_no?: string
  order_amount?: number
  buyer_id?: string
  ship_out_tracking_no?: string
  ship_in_tracking_no?: string
  scheduled_ship_time?: string
  express_type_id?: number
  
  // 附件选择（UI层使用数组表示）
  bundled_accessories: ('handle' | 'lens_mount')[]
  phone_holder_id: number | null
  tripod_id: number | null
}

/**
 * 租赁创建负载（API层）
 */
export interface RentalCreatePayload {
  device_id: number
  start_date: string
  end_date: string
  customer_name: string
  customer_phone?: string
  destination?: string
  xianyu_order_no?: string
  order_amount?: number
  buyer_id?: string
  ship_out_tracking_no?: string
  ship_in_tracking_no?: string
  scheduled_ship_time?: string
  express_type_id?: number
  
  // 配套附件（API层使用布尔值）
  includes_handle: boolean
  includes_lens_mount: boolean
  
  // 库存附件（API层使用ID数组）
  accessories: number[]
}

/**
 * 租赁更新负载（API层）
 */
export interface RentalUpdatePayload {
  customer_name?: string
  customer_phone?: string
  destination?: string
  start_date?: string
  end_date?: string
  xianyu_order_no?: string
  order_amount?: number
  buyer_id?: string
  ship_out_tracking_no?: string
  ship_in_tracking_no?: string
  scheduled_ship_time?: string
  express_type_id?: number
  status?: string
  
  // 配套附件
  includes_handle?: boolean
  includes_lens_mount?: boolean
  
  // 库存附件
  accessories?: number[]
}

/**
 * 附件信息（API响应）
 */
export interface AccessoryInfo {
  id?: number
  name: string
  type: 'handle' | 'lens_mount' | 'phone_holder' | 'tripod' | 'other'
  is_bundled: boolean
  serial_number?: string
}

/**
 * 租赁记录（API响应）
 */
export interface Rental {
  id: number
  device_id: number
  start_date: string
  end_date: string
  ship_out_time?: string | null
  ship_in_time?: string | null
  customer_name: string
  customer_phone?: string
  destination?: string
  xianyu_order_no?: string
  order_amount?: number
  buyer_id?: string
  ship_out_tracking_no?: string
  ship_in_tracking_no?: string
  scheduled_ship_time?: string | null
  express_type_id?: number
  status: 'not_shipped' | 'scheduled_for_shipping' | 'shipped' | 'returned' | 'completed' | 'cancelled'
  created_at: string
  updated_at: string
  
  // 配套附件标记
  includes_handle: boolean
  includes_lens_mount: boolean
  
  // 代传照片标记
  photo_transfer: boolean
  
  // 关联数据
  device?: any
  device_info?: any
  accessories?: AccessoryInfo[]
  parent_rental_id?: number | null
  child_rentals?: Rental[]
  
  // 计算属性
  duration_days?: number
  is_overdue?: boolean
}

/**
 * 设备可用性信息
 */
export interface DeviceAvailability {
  id: number
  name: string
  serial_number?: string
  is_available: boolean
  conflict_reason?: string
}

/**
 * 将UI层表单数据转换为API创建负载
 */
export function convertFormDataToCreatePayload(formData: RentalFormData): RentalCreatePayload {
  return {
    device_id: formData.device_id,
    start_date: formData.start_date,
    end_date: formData.end_date,
    customer_name: formData.customer_name,
    customer_phone: formData.customer_phone,
    destination: formData.destination,
    xianyu_order_no: formData.xianyu_order_no,
    order_amount: formData.order_amount,
    buyer_id: formData.buyer_id,
    ship_out_tracking_no: formData.ship_out_tracking_no,
    ship_in_tracking_no: formData.ship_in_tracking_no,
    scheduled_ship_time: formData.scheduled_ship_time,
    express_type_id: formData.express_type_id,
    
    // 将UI层的数组转换为API层的布尔值
    includes_handle: formData.bundled_accessories.includes('handle'),
    includes_lens_mount: formData.bundled_accessories.includes('lens_mount'),
    
    // 将UI层的单个ID转换为API层的数组（过滤null值）
    accessories: [formData.phone_holder_id, formData.tripod_id]
      .filter((id): id is number => id !== null)
  }
}

/**
 * 将API响应的租赁数据转换为UI层表单数据
 */
export function convertRentalToFormData(rental: Rental): Partial<RentalFormData> {
  // 从accessories数组中提取库存附件ID
  const phoneHolder = rental.accessories?.find(a => a.type === 'phone_holder')
  const tripod = rental.accessories?.find(a => a.type === 'tripod')
  
  // 将API层的布尔值转换为UI层的数组
  const bundled_accessories: ('handle' | 'lens_mount')[] = []
  if (rental.includes_handle) {
    bundled_accessories.push('handle')
  }
  if (rental.includes_lens_mount) {
    bundled_accessories.push('lens_mount')
  }
  
  return {
    device_id: rental.device_id,
    start_date: rental.start_date,
    end_date: rental.end_date,
    customer_name: rental.customer_name,
    customer_phone: rental.customer_phone,
    destination: rental.destination,
    xianyu_order_no: rental.xianyu_order_no,
    order_amount: rental.order_amount,
    buyer_id: rental.buyer_id,
    ship_out_tracking_no: rental.ship_out_tracking_no,
    ship_in_tracking_no: rental.ship_in_tracking_no,
    scheduled_ship_time: rental.scheduled_ship_time || undefined,
    express_type_id: rental.express_type_id,
    
    bundled_accessories,
    phone_holder_id: phoneHolder?.id || null,
    tripod_id: tripod?.id || null
  }
}
