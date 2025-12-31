/**
 * API客户端基础配置
 * 配置axios实例、拦截器和错误处理
 */

import axios, { AxiosError } from 'axios'
import type { ApiResponse } from '@/types'

// 创建axios实例
export const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '/api',
  timeout: 10000,
  headers: {
    'Content-Type': 'application/json'
  }
})

// 请求拦截器
apiClient.interceptors.request.use(
  (config) => {
    // 可以在这里添加token等
    return config
  },
  (error) => {
    return Promise.reject(error)
  }
)

// 响应拦截器
apiClient.interceptors.response.use(
  (response) => {
    // 统一处理响应数据
    return response.data
  },
  (error: AxiosError<ApiResponse>) => {
    // 统一错误处理
    const errorMessage = error.response?.data?.error || error.message || '网络请求失败'
    
    // 可以在这里添加全局错误提示
    console.error('API Error:', errorMessage)
    
    return Promise.reject(new Error(errorMessage))
  }
)

export default apiClient
