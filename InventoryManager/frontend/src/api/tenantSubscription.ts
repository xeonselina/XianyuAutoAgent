import { tenantCsrfHeaders } from '@/api/tenantIdentity'

export interface TenantSubscriptionStatus {
  effective_status: 'active' | 'expired'
  expires_at: string
  subscription_row_version: number
  can_redeem: boolean
}

export interface TenantSubscriptionRenewalResult {
  effective_status: 'active'
  expires_at: string
  subscription_row_version: number
  idempotent_replay: boolean
}

interface ApiEnvelope<T> {
  success: boolean
  data?: T
  message?: string
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init)
  const body = await response.json() as ApiEnvelope<T>
  if (!response.ok || !body.success || body.data === undefined) {
    throw new Error(body.message || '订阅操作失败')
  }
  return body.data
}

export const getTenantSubscriptionStatus = () =>
  request<TenantSubscriptionStatus>('/api/subscription/status')

export const redeemTenantSubscription = (payload: {
  code: string
  idempotency_key: string
  expected_subscription_row_version: number
}) => request<TenantSubscriptionRenewalResult>('/api/subscription/redeem', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    ...tenantCsrfHeaders(),
  },
  body: JSON.stringify(payload),
})
