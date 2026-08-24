import { tenantCsrfHeaders } from './tenantIdentity'

export type TenantIntegrationProvider = 'sf' | 'xianyu' | 'kuaimai'
export type TenantIntegrationCredentials = Record<string, string>

export interface TenantIntegrationSummary {
  integration_id: string
  provider: TenantIntegrationProvider
  name: string
  status: string
  configured: boolean
  last_verified_at: string | null
  row_version: number
}

export interface TenantIntegrationChallenge {
  intent_id: string
  challenge_id: string
  expires_at: string
  replayed: boolean
}

export interface TenantIntegrationCredentialResult {
  integration_id: string
  revision_id: string
  revision_no: number
  status: 'pending_validation'
  verification_status: 'not_attempted'
  validation_event_id: string
  idempotent: boolean
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
    throw new Error(body.message || '租户集成操作失败')
  }
  return body.data
}

const mutationHeaders = () => ({
  'Content-Type': 'application/json',
  ...tenantCsrfHeaders(),
})

export async function listTenantIntegrations(): Promise<TenantIntegrationSummary[]> {
  const result = await request<{ items: TenantIntegrationSummary[] }>(
    '/api/integrations',
  )
  return result.items
}

export function createTenantIntegration(payload: {
  integration_id: string
  provider: TenantIntegrationProvider
  name: string
}) {
  return request<TenantIntegrationSummary & { idempotent: boolean }>(
    '/api/integrations',
    {
      method: 'POST',
      headers: mutationHeaders(),
      body: JSON.stringify({ ...payload, config: {} }),
    },
  )
}

export function requestTenantIntegrationCredentialChallenge(
  integration: TenantIntegrationSummary,
  actionId: string,
  credentials: TenantIntegrationCredentials,
) {
  return request<TenantIntegrationChallenge>(
    `/api/integrations/${encodeURIComponent(integration.integration_id)}/credential-challenges`,
    {
      method: 'POST',
      headers: mutationHeaders(),
      body: JSON.stringify({
        action_id: actionId,
        expected_row_version: integration.row_version,
        credentials,
      }),
    },
  )
}

export function confirmTenantIntegrationCredentials(
  integration: TenantIntegrationSummary,
  payload: {
    action_id: string
    challenge_id: string
    code: string
    credentials: TenantIntegrationCredentials
  },
) {
  return request<TenantIntegrationCredentialResult>(
    `/api/integrations/${encodeURIComponent(integration.integration_id)}/credential-confirm`,
    {
      method: 'POST',
      headers: mutationHeaders(),
      body: JSON.stringify({
        ...payload,
        expected_row_version: integration.row_version,
      }),
    },
  )
}
