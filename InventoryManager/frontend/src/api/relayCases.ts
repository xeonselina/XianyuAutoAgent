import axios from 'axios'

import type {
  RelayCaseListParams,
  RelayCaseListResponse,
  RelayCaseMutationResponse,
  RelayCaseStatus,
  ManualRelayOptionsResponse,
  RelayTracking,
  RelayTrackingBatchResponse,
} from '@/types/relayCase'

interface ApiResponse<T> {
  success: boolean
  data?: T
  message?: string
}

function unwrap<T>(response: { data: ApiResponse<T> }): T {
  if (!response.data.success || response.data.data === undefined) {
    throw new Error(response.data.message || '请求失败')
  }
  return response.data.data
}

async function request<T>(
  pending: Promise<{ data: ApiResponse<T> }>,
): Promise<T> {
  try {
    return unwrap(await pending)
  } catch (error) {
    const response = (error as {
      response?: { data?: { message?: unknown } }
    } | null)?.response
    const message = response?.data?.message
    if (typeof message === 'string' && message.trim()) {
      throw new Error(message)
    }
    throw error
  }
}

export async function listRelayCases(
  params: RelayCaseListParams,
): Promise<RelayCaseListResponse> {
  return request(axios.get<ApiResponse<RelayCaseListResponse>>(
    '/api/relay-cases',
    {
      params: {
        statuses: params.statuses.join(','),
        ship_date_from: params.shipDateFrom,
        ship_date_to: params.shipDateTo,
        page: params.page,
        per_page: params.perPage,
      },
    },
  ))
}

export async function updateRelayCase(
  predecessorId: number,
  successorId: number,
  payload: {
    status: RelayCaseStatus
    sf_tracking_number?: string
  },
): Promise<RelayCaseMutationResponse> {
  return request(axios.put<ApiResponse<RelayCaseMutationResponse>>(
    `/api/relay-cases/${predecessorId}/${successorId}`,
    payload,
  ))
}

export async function listManualRelayOptions(): Promise<ManualRelayOptionsResponse> {
  return request(axios.get<ApiResponse<ManualRelayOptionsResponse>>(
    '/api/relay-cases/manual-options',
  ))
}

export async function createManualRelayCase(
  deviceId: number,
): Promise<RelayCaseMutationResponse> {
  return request(axios.post<ApiResponse<RelayCaseMutationResponse>>(
    '/api/relay-cases/manual',
    { device_id: deviceId },
  ))
}

export async function refreshRelayTracking(
  caseId: number,
): Promise<RelayTracking> {
  return request(axios.post<ApiResponse<RelayTracking>>(
    `/api/relay-cases/${caseId}/tracking/refresh`,
  ))
}

export async function refreshRelayTrackingBatch(
  caseIds: number[],
): Promise<RelayTrackingBatchResponse> {
  return request(axios.post<ApiResponse<RelayTrackingBatchResponse>>(
    '/api/relay-cases/tracking/refresh-batch',
    { case_ids: caseIds },
  ))
}
