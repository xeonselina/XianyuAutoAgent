/**
 * 验货 API 服务
 */

import type {
  LatestRentalResponse,
  InspectionRecord,
  CreateInspectionRequest,
  UpdateInspectionRequest,
  InspectionListParams,
  InspectionListResponse
} from '../types/inspection'

/**
 * API 基础 URL
 */
const API_BASE_URL = '/api/inspections'

/**
 * 根据设备ID获取最近的租赁记录和动态检查清单
 * @param deviceId 设备ID
 */
export async function getLatestRentalByDeviceId(deviceId: number) {
  const response = await fetch(`${API_BASE_URL}/rental/latest/${deviceId}`)
  return await response.json() as { success: boolean; data?: LatestRentalResponse; message?: string }
}

/**
 * 根据设备名称获取最近的租赁记录和动态检查清单
 * @param deviceName 设备名称（纯数字）
 */
export async function getLatestRentalByDeviceName(deviceName: string) {
  const response = await fetch(`${API_BASE_URL}/rental/latest/by-name/${encodeURIComponent(deviceName)}`)
  return await response.json() as { success: boolean; data?: LatestRentalResponse; message?: string }
}

/**
 * 创建验货记录
 * @param data 验货记录数据
 */
export async function createInspection(data: CreateInspectionRequest) {
  const response = await fetch(API_BASE_URL, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify(data)
  })
  return await response.json() as { success: boolean; data?: InspectionRecord; message?: string }
}

/**
 * 获取验货记录详情
 * @param id 验货记录ID
 */
export async function getInspectionById(id: number) {
  const response = await fetch(`${API_BASE_URL}/${id}`)
  return await response.json() as { success: boolean; data?: InspectionRecord; message?: string }
}

/**
 * 更新验货记录
 * @param id 验货记录ID
 * @param data 更新数据
 */
export async function updateInspection(id: number, data: UpdateInspectionRequest) {
  const response = await fetch(`${API_BASE_URL}/${id}`, {
    method: 'PUT',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify(data)
  })
  return await response.json() as { success: boolean; data?: InspectionRecord; message?: string }
}

/**
 * 获取验货记录列表（支持筛选和分页）
 * @param params 查询参数
 */
export async function getInspectionList(params?: InspectionListParams) {
  const queryParams = new URLSearchParams()
  if (params) {
    if (params.device_name) queryParams.set('device_name', params.device_name)
    if (params.status) queryParams.set('status', params.status)
    if (params.page) queryParams.set('page', params.page.toString())
    if (params.per_page) queryParams.set('per_page', params.per_page.toString())
  }
  
  const url = params ? `${API_BASE_URL}?${queryParams.toString()}` : API_BASE_URL
  const response = await fetch(url)
  return await response.json() as { success: boolean; data?: InspectionListResponse; message?: string }
}
