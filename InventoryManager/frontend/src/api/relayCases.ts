import axios from 'axios'

import type {
  RelayCaseListParams,
  RelayCaseListResponse,
  RelayCaseMutationResponse,
  RelayCaseStatus,
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

export async function listRelayCases(
  params: RelayCaseListParams,
): Promise<RelayCaseListResponse> {
  const response = await axios.get<ApiResponse<RelayCaseListResponse>>(
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
  )
  return unwrap(response)
}

export async function updateRelayCase(
  predecessorId: number,
  successorId: number,
  payload: {
    status: RelayCaseStatus
    sf_tracking_number?: string
  },
): Promise<RelayCaseMutationResponse> {
  const response = await axios.put<ApiResponse<RelayCaseMutationResponse>>(
    `/api/relay-cases/${predecessorId}/${successorId}`,
    payload,
  )
  return unwrap(response)
}

export async function refreshRelayTracking(
  caseId: number,
): Promise<RelayTracking> {
  const response = await axios.post<ApiResponse<RelayTracking>>(
    `/api/relay-cases/${caseId}/tracking/refresh`,
  )
  return unwrap(response)
}

export async function refreshRelayTrackingBatch(
  caseIds: number[],
): Promise<RelayTrackingBatchResponse> {
  const response = await axios.post<ApiResponse<RelayTrackingBatchResponse>>(
    '/api/relay-cases/tracking/refresh-batch',
    { case_ids: caseIds },
  )
  return unwrap(response)
}
