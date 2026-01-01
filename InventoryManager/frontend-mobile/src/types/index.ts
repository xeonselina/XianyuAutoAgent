/**
 * 移动端前端 TypeScript 类型定义
 * 复用后端数据模型
 */

// 设备状态
export type DeviceStatus = 'online' | 'offline'

// 租赁状态
export type RentalStatus = 
  | 'not_shipped'
  | 'scheduled_for_shipping'
  | 'shipped'
  | 'returned'
  | 'completed'
  | 'cancelled'

// 设备型号
export interface DeviceModel {
  id: number
  name: string
  display_name: string | null
  description: string | null
}

// 设备
export interface Device {
  id: number
  name: string
  serial_number: string
  model: string
  model_id: number | null
  is_accessory: boolean
  status: DeviceStatus
  device_model?: DeviceModel
  created_at: string
  updated_at: string
}

// 租赁记录
export interface Rental {
  id: number
  device_id: number
  start_date: string            // ISO date string (YYYY-MM-DD)
  end_date: string              // ISO date string (YYYY-MM-DD)
  ship_out_time: string | null  // ISO datetime string
  ship_in_time: string | null   // ISO datetime string
  customer_name: string
  customer_phone: string | null
  destination: string | null
  xianyu_order_no: string | null
  order_amount: number | null
  buyer_id: string | null
  ship_out_tracking_no: string | null
  ship_in_tracking_no: string | null
  scheduled_ship_time: string | null
  express_type_id: number
  status: RentalStatus
  created_at: string
  updated_at: string
}

// 甘特图设备(包含租赁记录)
export interface GanttDevice extends Device {
  rentals: Rental[]
}

// 甘特图数据
export interface GanttData {
  devices: GanttDevice[]
  rentals: Rental[]
  date_range: {
    start: string
    end: string
  }
  today: string
}

// API响应基础类型
export interface ApiResponse<T = any> {
  success: boolean
  data?: T
  error?: string
  message?: string
}

// 移动端甘特图时间轴块
export interface TimelineBlock {
  rental: Rental
  left: number       // 相对位置 (像素)
  width: number      // 宽度 (像素)
  color: string      // 颜色
}

// 预约表单数据
export interface RentalFormData {
  device_id: number | null
  start_date: string
  end_date: string
  customer_name: string
  customer_phone: string
  destination: string
  xianyu_order_no?: string
  order_amount?: number
}
