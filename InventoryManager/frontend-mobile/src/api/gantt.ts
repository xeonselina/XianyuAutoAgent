/**
 * 甘特图相关 API
 */

import { apiClient } from './client'
import type { ApiResponse, GanttData } from '@/types'

/**
 * 获取甘特图数据
 */
export interface GetGanttDataParams {
  start_date?: string
  end_date?: string
}

export const getGanttData = (params?: GetGanttDataParams) => {
  return apiClient.get<ApiResponse<GanttData>>('/gantt/data', { params })
}

/**
 * 获取每日统计数据
 */
export interface DailyStatsParams {
  date: string
  device_model?: string
}

export interface DailyStats {
  available_count: number
  ship_out_count: number
  accessory_ship_out_count: number
}

export const getDailyStats = (params: DailyStatsParams) => {
  return apiClient.get<ApiResponse<DailyStats>>('/gantt/daily-stats', { params })
}
