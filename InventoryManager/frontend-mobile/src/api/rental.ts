/**
 * 租赁相关 API
 */

import { apiClient } from './client'
import type { ApiResponse, Rental, RentalFormData } from '@/types'

/**
 * 获取所有租赁记录
 */
export const getRentals = () => {
  return apiClient.get<ApiResponse<Rental[]>>('/rentals')
}

/**
 * 获取单个租赁详情
 */
export const getRentalById = (id: number) => {
  return apiClient.get<ApiResponse<Rental>>(`/rentals/${id}`)
}

/**
 * 创建租赁记录
 */
export const createRental = (data: RentalFormData) => {
  return apiClient.post<ApiResponse<Rental>>('/rentals', data)
}

/**
 * 更新租赁记录
 */
export const updateRental = (id: number, data: Partial<RentalFormData>) => {
  return apiClient.put<ApiResponse<Rental>>(`/rentals/${id}`, data)
}

/**
 * 删除租赁记录
 */
export const deleteRental = (id: number) => {
  return apiClient.delete<ApiResponse<void>>(`/rentals/${id}`)
}

/**
 * 查找可用档期
 */
export interface FindSlotParams {
  start_date: string
  end_date: string
  logistics_days: number
  model: string
  is_accessory: boolean
}

export interface FindSlotResponse {
  available_devices: Array<{
    id: number
    name: string
    serial_number: string
  }>
  ship_out_date: string
  ship_in_date: string
}

export const findAvailableSlot = (params: FindSlotParams) => {
  return apiClient.post<ApiResponse<FindSlotResponse>>('/rentals/find-slot', params)
}

/**
 * 检查租赁冲突
 */
export interface CheckConflictParams {
  device_id: number
  ship_out_time: string
  ship_in_time: string
  exclude_rental_id?: number
}

export const checkConflict = (params: CheckConflictParams) => {
  return apiClient.post<ApiResponse<{ has_conflicts: boolean }>>('/rentals/check-conflict', params)
}

/**
 * 检查重复租赁
 */
export interface CheckDuplicateParams {
  customer_name: string
  destination: string
  start_date: string
  end_date: string
  exclude_rental_id?: number
}

export const checkDuplicate = (params: CheckDuplicateParams) => {
  return apiClient.post<ApiResponse<{ has_duplicate: boolean; duplicates: Rental[] }>>('/rentals/check-duplicate', params)
}
