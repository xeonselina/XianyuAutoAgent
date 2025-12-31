/**
 * 设备相关 API
 */

import { apiClient } from './client'
import type { ApiResponse, Device, DeviceModel } from '@/types'

/**
 * 获取所有设备列表
 */
export const getDevices = () => {
  return apiClient.get<ApiResponse<Device[]>>('/devices')
}

/**
 * 获取单个设备详情
 */
export const getDeviceById = (id: number) => {
  return apiClient.get<ApiResponse<Device>>(`/devices/${id}`)
}

/**
 * 获取所有设备型号
 */
export const getDeviceModels = () => {
  return apiClient.get<ApiResponse<DeviceModel[]>>('/device-models')
}

/**
 * 获取指定型号的配件
 */
export const getModelAccessories = (modelId: number) => {
  return apiClient.get<ApiResponse<Device[]>>(`/device-models/${modelId}/accessories`)
}
