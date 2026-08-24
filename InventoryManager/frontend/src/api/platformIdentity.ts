export type PlatformFactorMethod = 'totp' | 'recovery_code'

export interface PlatformLoginResult {
  csrf_token: string
  session_id: string
  role: 'platform_admin'
  mfa_method: PlatformFactorMethod
}

export interface PlatformStepUpResult extends PlatformLoginResult {
  mfa_verified_at: string
}

export interface PlatformSessionStatus {
  session_id: string
  platform_admin_id: string
  username: string
  role: 'platform_admin'
  mfa_method: PlatformFactorMethod
}

export interface PlatformSessionDevice {
  session_id: string
  device_name: string | null
  mfa_method: PlatformFactorMethod
  created_at: string
  last_seen_at: string
  idle_expires_at: string
  absolute_expires_at: string
  current: boolean
}

export interface PlatformTotpSetup {
  credential_id: string
  base32_seed: string
}

export interface PlatformRecoveryCodeBatch {
  recovery_code_generation: number
  recovery_codes: string[]
}

export interface PlatformTotpReplacementResult extends PlatformRecoveryCodeBatch {
  totp_generation: number
  revoked_session_count: number
}

export interface PlatformTenantDirectoryItem {
  tenant_id: string
  name: string | null
  slug: string | null
  status: string
  timezone: string
  tenant_row_version: number
  subscription_status: string | null
  subscription_expires_at: string | null
  subscription_row_version: number | null
  database_status: string | null
  updated_at: string
}

export interface PlatformTenantDirectoryPage {
  items: PlatformTenantDirectoryItem[]
  page: number
  page_size: number
  has_more: boolean
  status_filter: string | null
}

export interface PlatformTenantDetail {
  tenant_id: string
  name: string | null
  slug: string | null
  public_identity_published_at: string | null
  status: string
  access_version: number
  tenant_row_version: number
  timezone: string
  locale: string
  created_at: string
  updated_at: string
  subscription: null | {
    subscription_id: string
    status: string
    expires_at: string
    row_version: number
  }
  database_route: null | {
    database_uuid: string
    status: string
    schema_version: string | null
    route_version: number
    dml_desired_login_state: string | null
    dml_observed_login_state: string | null
    dml_login_state_version: number | null
    platform_read_route_version: number | null
  }
}

export interface PlatformTenantRentalItem {
  rental_id: number
  device: {
    device_id: number
    name: string
    model: string
  }
  start_date: string | null
  end_date: string | null
  status: string
  customer: {
    name_masked: string | null
    phone_masked: string | null
    region_masked: string | null
  }
  order_amount: string | null
  actual_shipped_at: string | null
  actual_returned_at: string | null
  created_at: string | null
  updated_at: string | null
}

export interface PlatformTenantRentalPage {
  items: PlatformTenantRentalItem[]
  page: number
  page_size: number
  has_more: boolean
  status_filter: string | null
}

export interface PlatformTenantDeviceItem {
  device_id: number
  name: string
  model: string
  model_id: number | null
  is_accessory: boolean
  warehouse_id: number | null
  lifecycle_status: string
  lifecycle_date: string | null
  created_at: string | null
  updated_at: string | null
}

export interface PlatformTenantDevicePage {
  items: PlatformTenantDeviceItem[]
  page: number
  page_size: number
  has_more: boolean
  lifecycle_status_filter: string | null
}

export interface PlatformTenantWarehouseItem {
  warehouse_id: number
  warehouse_uuid: string
  name: string | null
  status: string
  setup_state: string
  is_default: boolean
  created_at: string | null
  updated_at: string | null
}

export interface PlatformTenantWarehousePage {
  items: PlatformTenantWarehouseItem[]
  page: number
  page_size: number
  has_more: boolean
  status_filter: string | null
  setup_state_filter: string | null
}

export interface PlatformTenantCustomerPii {
  rental_id: number
  customer: {
    name: string | null
    phone: string | null
    address: {
      province: string | null
      city: string | null
      district: string | null
      detail: string | null
    }
  }
}

export type PlatformSubscriptionAdjustmentOperation =
  | 'add_days'
  | 'subtract_days'
  | 'expire_now'

export interface PlatformSubscriptionAdjustmentInput {
  operation: PlatformSubscriptionAdjustmentOperation
  days: number | null
  reason_code: string
  note: string | null
  offline_reference: string | null
  idempotency_key: string
}

export interface PlatformSubscriptionAdjustmentPreview {
  action_id: string
  confirmation_token: string
  operation: PlatformSubscriptionAdjustmentOperation
  days: number | null
  database_effective_at: string
  calculation_base_at: string
  before_expires_at: string
  after_expires_at: string
  before_status: 'active' | 'expired'
  after_status: 'active' | 'expired'
  expected_tenant_row_version: number
  expected_subscription_row_version: number
  expires_at: string
}

export interface PlatformSubscriptionAdjustmentResult {
  tenant_id: string
  subscription_id: string
  event_id: string
  action_id: string
  operation: PlatformSubscriptionAdjustmentOperation
  signed_delta_days: number | null
  database_effective_at: string
  calculation_base_at: string
  before_expires_at: string
  after_expires_at: string
  before_status: 'active' | 'expired'
  after_status: 'active' | 'expired'
  resulting_subscription_row_version: number
  created: boolean
  refund_disclaimer: string
}

export type PlatformRedemptionCodeStatus =
  | 'active'
  | 'reserved'
  | 'redeemed'
  | 'revoked'
  | 'expired'
  | 'recovery_revoked'

export interface PlatformRedemptionCodeItem {
  code_id: string
  batch_id: string
  batch_name: string
  channel: string | null
  internal_note: string | null
  masked_code: string
  status: PlatformRedemptionCodeStatus
  row_version: number
  plan_revision_id: string
  service_duration_seconds: number
  redeem_before: string
  created_at: string
  reserved_attempt_id: string | null
  reserved_attempt_status: string | null
  redeemed_tenant_id: string | null
  redeemed_user_id: string | null
  redeemed_at: string | null
  revocation_reason_code: string | null
  replacement_status: 'issued' | 'integrity_blocked' | null
  replacement_code_id: string | null
}

export interface PlatformRedemptionCodePage {
  items: PlatformRedemptionCodeItem[]
  page: number
  page_size: number
  total: number
  pages: number
}

export interface PlatformRedemptionBatchResult {
  batch_id: string
  created: boolean
  quantity: number
  export_filename: string | null
  export_csv: string | null
}

interface ApiEnvelope<T> {
  success: boolean
  data?: T
  message?: string
}

const PLATFORM_CSRF_STORAGE_KEY = 'inventory_platform_csrf_v1'
const PLATFORM_CSRF_HEADER = 'X-Platform-CSRF-Token'
const PLATFORM_SETUP_HEADER = 'X-Platform-Setup-Token'

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init)
  let body: ApiEnvelope<T> | undefined
  try {
    body = await response.json() as ApiEnvelope<T>
  } catch {
    body = undefined
  }
  if (!response.ok || !body?.success || body.data === undefined) {
    throw new Error(body?.message || '平台身份操作失败')
  }
  return body.data
}

export function storePlatformCsrfToken(token: string): void {
  if (!token.trim()) throw new Error('平台 CSRF token 不能为空')
  sessionStorage.setItem(PLATFORM_CSRF_STORAGE_KEY, token)
}

export function clearPlatformCsrfToken(): void {
  sessionStorage.removeItem(PLATFORM_CSRF_STORAGE_KEY)
}

export function platformCsrfHeaders(): Record<string, string> {
  const token = sessionStorage.getItem(PLATFORM_CSRF_STORAGE_KEY)
  if (!token) throw new Error('平台登录验证已失效，请重新登录')
  return { [PLATFORM_CSRF_HEADER]: token }
}

function platformSetupHeaders(setupToken: string): Record<string, string> {
  if (!setupToken.trim()) throw new Error('setup token 不能为空')
  return { [PLATFORM_SETUP_HEADER]: setupToken }
}

export async function loginPlatformAdmin(payload: {
  username: string
  password: string
  factor_method: PlatformFactorMethod
  factor: string
  device_name?: string
}): Promise<PlatformLoginResult> {
  const result = await request<PlatformLoginResult>('/platform/api/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  storePlatformCsrfToken(result.csrf_token)
  return result
}

export const getPlatformSessionStatus = () =>
  request<PlatformSessionStatus>('/platform/api/session')

export async function stepUpPlatformSession(payload: {
  factor_method: PlatformFactorMethod
  factor: string
}): Promise<PlatformStepUpResult> {
  const result = await request<PlatformStepUpResult>('/platform/api/step-up', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...platformCsrfHeaders(),
    },
    body: JSON.stringify(payload),
  })
  storePlatformCsrfToken(result.csrf_token)
  return result
}

const postPlatformAction = <T>(url: string, payload: object) => request<T>(url, {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    ...platformCsrfHeaders(),
  },
  body: JSON.stringify(payload),
})

export const beginPlatformTotpReplacement = (payload: {
  factor_method: PlatformFactorMethod
  factor: string
}) => postPlatformAction<PlatformTotpSetup>(
  '/platform/api/factors/totp/replacement',
  payload,
)

export async function completePlatformTotpReplacement(
  credentialId: string,
  totpCode: string,
): Promise<PlatformTotpReplacementResult> {
  const result = await postPlatformAction<PlatformTotpReplacementResult>(
    '/platform/api/factors/totp/replacement/complete',
    { credential_id: credentialId, totp_code: totpCode },
  )
  clearPlatformCsrfToken()
  return result
}

export const regeneratePlatformRecoveryCodes = (payload: {
  factor_method: PlatformFactorMethod
  factor: string
}) => postPlatformAction<PlatformRecoveryCodeBatch>(
  '/platform/api/factors/recovery-codes/regenerate',
  payload,
)

export async function listPlatformSessions(): Promise<PlatformSessionDevice[]> {
  const result = await request<{ sessions: PlatformSessionDevice[] }>(
    '/platform/api/sessions',
  )
  return result.sessions
}

export const listPlatformTenants = (query: {
  page: number
  page_size: number
  status?: string
}) => {
  const parameters = new URLSearchParams({
    page: String(query.page),
    page_size: String(query.page_size),
  })
  if (query.status) parameters.set('status', query.status)
  return request<PlatformTenantDirectoryPage>(
    `/platform/api/tenants?${parameters.toString()}`,
  )
}

export const getPlatformTenant = (tenantId: string, signal?: AbortSignal) =>
  request<PlatformTenantDetail>(
    `/platform/api/tenants/${encodeURIComponent(tenantId)}`,
    signal ? { signal } : undefined,
  )

export const listPlatformTenantRentals = (
  tenantId: string,
  query: { page: number; page_size: number; status?: string },
  signal?: AbortSignal,
) => platformTenantPagedRead<PlatformTenantRentalPage>(
  tenantId,
  'rentals',
  query,
  signal,
)

export const listPlatformTenantDevices = (
  tenantId: string,
  query: { page: number; page_size: number; lifecycle_status?: string },
  signal?: AbortSignal,
) => platformTenantPagedRead<PlatformTenantDevicePage>(
  tenantId,
  'devices',
  query,
  signal,
)

export const listPlatformTenantWarehouses = (
  tenantId: string,
  query: {
    page: number
    page_size: number
    status?: string
    setup_state?: string
  },
  signal?: AbortSignal,
) => platformTenantPagedRead<PlatformTenantWarehousePage>(
  tenantId,
  'warehouses',
  query,
  signal,
)

const platformTenantPagedRead = <T>(
  tenantId: string,
  resource: 'rentals' | 'devices' | 'warehouses',
  query: Record<string, number | string | undefined>,
  signal?: AbortSignal,
) => {
  const parameters = new URLSearchParams({
    page: String(query.page),
    page_size: String(query.page_size),
  })
  Object.entries(query).forEach(([key, value]) => {
    if (key !== 'page' && key !== 'page_size' && value !== undefined) {
      parameters.set(key, String(value))
    }
  })
  return request<T>(
    `/platform/api/tenants/${encodeURIComponent(tenantId)}`
      + `/read/${resource}?${parameters.toString()}`,
    signal ? { signal } : undefined,
  )
}

export const getPlatformTenantRentalCustomerPii = (
  tenantId: string,
  rentalId: number,
  reason: string,
  signal?: AbortSignal,
) => {
  const parameters = new URLSearchParams({ reason })
  return request<PlatformTenantCustomerPii>(
    `/platform/api/tenants/${encodeURIComponent(tenantId)}`
      + `/read/rentals/${encodeURIComponent(String(rentalId))}`
      + `/customer-pii?${parameters.toString()}`,
    signal ? { signal } : undefined,
  )
}

export const logoutPlatformSession = () =>
  request<{ revoked: boolean }>('/platform/api/logout', {
    method: 'POST',
    headers: platformCsrfHeaders(),
  })

export const revokePlatformSession = (sessionId: string) =>
  request<{ revoked: boolean; current_session_revoked: boolean }>(
    `/platform/api/sessions/${encodeURIComponent(sessionId)}/revoke`,
    { method: 'POST', headers: platformCsrfHeaders() },
  )

export const revokeAllPlatformSessions = () =>
  request<{ revoked_count: number }>('/platform/api/sessions/revoke-all', {
    method: 'POST',
    headers: platformCsrfHeaders(),
  })

export const consumePlatformSetupToken = (setupToken: string) =>
  request<{ accepted: true }>('/platform/api/setup/consume', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ setup_token: setupToken }),
  })

export const setPlatformSetupPassword = (
  setupToken: string,
  password: string,
) => request<{ password_set: true }>('/platform/api/setup/password', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    ...platformSetupHeaders(setupToken),
  },
  body: JSON.stringify({ password }),
})

export const beginPlatformTotpSetup = (setupToken: string) =>
  request<PlatformTotpSetup>('/platform/api/setup/totp', {
    method: 'POST',
    headers: platformSetupHeaders(setupToken),
  })

export const completePlatformSetup = (
  setupToken: string,
  credentialId: string,
  totpCode: string,
) => request<{ setup_completed: true; recovery_codes: string[] }>(
  '/platform/api/setup/complete',
  {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...platformSetupHeaders(setupToken),
    },
    body: JSON.stringify({
      credential_id: credentialId,
      totp_code: totpCode,
    }),
  },
)

export const previewPlatformSubscriptionAdjustment = (
  tenantId: string,
  payload: PlatformSubscriptionAdjustmentInput,
) => postPlatformAction<PlatformSubscriptionAdjustmentPreview>(
  `/platform/api/tenants/${encodeURIComponent(tenantId)}`
    + '/subscription-adjustments/preview',
  payload,
)

export const commitPlatformSubscriptionAdjustment = (
  tenantId: string,
  payload: PlatformSubscriptionAdjustmentInput & {
    action_id: string
    expected_subscription_row_version: number
    confirmation_token: string
    factor_method: PlatformFactorMethod
    factor: string
  },
) => postPlatformAction<PlatformSubscriptionAdjustmentResult>(
  `/platform/api/tenants/${encodeURIComponent(tenantId)}`
    + '/subscription-adjustments',
  payload,
)

export const listPlatformRedemptionCodes = (query: {
  page: number
  page_size: number
  status?: PlatformRedemptionCodeStatus
}) => {
  const parameters = new URLSearchParams({
    page: String(query.page),
    page_size: String(query.page_size),
  })
  if (query.status) parameters.set('status', query.status)
  return request<PlatformRedemptionCodePage>(
    `/platform/api/redemption-codes?${parameters.toString()}`,
  )
}

export const generatePlatformRedemptionCodeBatch = (payload: {
  generation_request_id: string
  name: string
  quantity: number
  service_duration_days: number
  redeem_before: string
  channel?: string | null
  internal_note?: string | null
}) => postPlatformAction<PlatformRedemptionBatchResult>(
  '/platform/api/redemption-code-batches',
  payload,
)

export const revealPlatformRedemptionCode = (codeId: string) =>
  postPlatformAction<{
    code_id: string
    code: string
    status: PlatformRedemptionCodeStatus
    row_version: number
  }>(
    `/platform/api/redemption-codes/${encodeURIComponent(codeId)}/reveal`,
    {},
  )

export const revokePlatformRedemptionCode = (
  codeId: string,
  payload: { expected_row_version: number; reason_code: string },
) => postPlatformAction<{
  code_id: string
  status: 'revoked'
  row_version: number
  changed: boolean
}>(
  `/platform/api/redemption-codes/${encodeURIComponent(codeId)}/revoke`,
  payload,
)
