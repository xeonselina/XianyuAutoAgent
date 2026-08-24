export interface TenantSessionDevice {
  session_id: string
  device_summary: string
  created_at: string
  last_seen_at: string
  is_current: boolean
}

export interface TenantMemberSummary {
  membership_id: string
  role: 'admin' | 'operator'
  status: 'active' | 'disabled'
  masked_phone: string
  row_version: number
}

export interface TenantInvitationSummary {
  invitation_id: string
  role: 'admin' | 'operator'
  status: 'pending' | 'accepted' | 'revoked' | 'expired' | 'superseded'
  phone: string
  masked_phone: string
  token_generation: number
  expires_at: string
  row_version: number
  created_at: string
}

export interface TenantMemberDirectory {
  seat_usage: {
    active_members: number
    pending_invitations: number
    used: number
    limit: number
  }
  members: TenantMemberSummary[]
  invitations: TenantInvitationSummary[]
}

export type TenantMemberMutationAction =
  | 'enable'
  | 'disable'
  | 'release'
  | 'change_role'

export interface TenantMemberMutationResult {
  membership_id: string
  role: 'admin' | 'operator'
  status: 'active' | 'disabled' | 'released'
  row_version: number
  sessions_revoked: number
  idempotent: boolean
}

export interface TenantMemberMutationChallenge {
  intent_id: string
  challenge_id: string
  expires_at: string
  replayed: boolean
}

export interface TenantInvitationCredential {
  invitation_id: string
  token: string
  generation: number
}

export interface TenantInvitationPublicSummary {
  invitation_id: string
  tenant_name: string
  role: 'admin' | 'operator'
  masked_phone: string
  expires_at: string
}

export interface TenantSessionStatus {
  authenticated: true
  session_id: string
  tenant_id: string
  role: 'admin' | 'operator'
  effective_gate: 'active' | 'expired' | 'suspended'
  tenant_timezone: string
}

export interface TenantLoginChallenge {
  challenge_id: string
  expires_in_seconds: number
  resend_after_seconds: number
}

export interface TenantLoginResult extends TenantSessionStatus {
  csrf_token: string
}

export interface TenantPhoneChangeChallenge {
  intent_id: string
  old_challenge_id: string
  new_challenge_id: string
  expires_at: string
  replayed: boolean
}

export interface TenantPhoneChangeResult {
  phone_changed: true
  user_id: string
  auth_version: number
  sessions_revoked: number
  invitations_superseded: number
  login_required: true
}

interface ApiEnvelope<T> {
  success: boolean
  data?: T
  message?: string
}

const CSRF_STORAGE_KEY = 'inventory_tenant_csrf_v1'

export function storeTenantCsrfToken(token: string): void {
  if (!token.trim()) throw new Error('CSRF token 不能为空')
  sessionStorage.setItem(CSRF_STORAGE_KEY, token)
}

export function clearTenantCsrfToken(): void {
  sessionStorage.removeItem(CSRF_STORAGE_KEY)
}

export function tenantCsrfHeaders(): Record<string, string> {
  const token = sessionStorage.getItem(CSRF_STORAGE_KEY)
  if (!token) throw new Error('登录验证已失效，请重新登录')
  return { 'X-CSRF-Token': token }
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init)
  const body = await response.json() as ApiEnvelope<T>
  if (!response.ok || !body.success || body.data === undefined) {
    throw new Error(body.message || '账号安全操作失败')
  }
  return body.data
}

export const getTenantSessionStatus = () =>
  request<TenantSessionStatus>('/api/auth/session')

export const requestTenantLoginCode = (phone: string) =>
  request<TenantLoginChallenge>('/api/auth/login/challenges', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ phone }),
  })

export const verifyTenantLoginCode = async (payload: {
  phone: string
  challenge_id: string
  code: string
  device_name?: string
}) => {
  const result = await request<TenantLoginResult>('/api/auth/login/verify', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  storeTenantCsrfToken(result.csrf_token)
  return result
}

export const listTenantSessions = async () => {
  const data = await request<{ sessions: TenantSessionDevice[] }>(
    '/api/auth/sessions',
  )
  return data.sessions
}

export const logoutCurrentSession = async () =>
  request<{ logged_out: true; revoked: boolean }>('/api/auth/logout', {
    method: 'POST',
    headers: tenantCsrfHeaders(),
  })

export const revokeTenantSession = async (sessionId: string) =>
  request<{ revoked: boolean; current_session_revoked: boolean }>(
    `/api/auth/sessions/${encodeURIComponent(sessionId)}/revoke`,
    { method: 'POST', headers: tenantCsrfHeaders() },
  )

export const revokeAllTenantSessions = async () =>
  request<{ revoked_count: number; all_sessions_revoked: true }>(
    '/api/auth/sessions/revoke-all',
    { method: 'POST', headers: tenantCsrfHeaders() },
  )

export const requestTenantPhoneChange = (
  newPhone: string,
  actionId: string,
) => request<TenantPhoneChangeChallenge>('/api/auth/phone-change/challenges', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json', ...tenantCsrfHeaders() },
  body: JSON.stringify({ new_phone: newPhone, action_id: actionId }),
})

export const confirmTenantPhoneChange = (payload: {
  new_phone: string
  action_id: string
  old_challenge_id: string
  old_code: string
  new_challenge_id: string
  new_code: string
}) => request<TenantPhoneChangeResult>('/api/auth/phone-change/confirm', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json', ...tenantCsrfHeaders() },
  body: JSON.stringify(payload),
})

export const getTenantMemberDirectory = () =>
  request<TenantMemberDirectory>('/api/v1/members')

export const mutateTenantMember = (
  member: TenantMemberSummary,
  action: Exclude<TenantMemberMutationAction, 'change_role'>,
) => request<TenantMemberMutationResult>(
  `/api/v1/members/${encodeURIComponent(member.membership_id)}/mutations`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json', ...tenantCsrfHeaders() },
  body: JSON.stringify({
    action,
    action_id: crypto.randomUUID(),
    expected_row_version: member.row_version,
  }),
})

const memberMutationPayload = (
  member: TenantMemberSummary,
  action: TenantMemberMutationAction,
  actionId: string,
  targetRole?: 'admin' | 'operator',
) => ({
  action,
  action_id: actionId,
  expected_row_version: member.row_version,
  target_role: targetRole,
})

export const requestTenantMemberMutationChallenge = (
  member: TenantMemberSummary,
  action: TenantMemberMutationAction,
  actionId: string,
  targetRole?: 'admin' | 'operator',
) => request<TenantMemberMutationChallenge>(
  `/api/v1/members/${encodeURIComponent(member.membership_id)}/mutations/challenge`,
  {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...tenantCsrfHeaders() },
    body: JSON.stringify(
      memberMutationPayload(member, action, actionId, targetRole),
    ),
  },
)

export const confirmTenantMemberMutation = (
  member: TenantMemberSummary,
  action: TenantMemberMutationAction,
  actionId: string,
  challengeId: string,
  code: string,
  targetRole?: 'admin' | 'operator',
) => request<TenantMemberMutationResult>(
  `/api/v1/members/${encodeURIComponent(member.membership_id)}/mutations/confirm`,
  {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...tenantCsrfHeaders() },
    body: JSON.stringify({
      ...memberMutationPayload(member, action, actionId, targetRole),
      challenge_id: challengeId,
      code,
    }),
  },
)

export const requestAdminInvitationChallenge = (phone: string, actionId: string) =>
  request<TenantMemberMutationChallenge>('/api/v1/members/invitations/admin-challenge', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...tenantCsrfHeaders() },
    body: JSON.stringify({ phone, role: 'admin', action_id: actionId }),
  })

export const createTenantInvitation = (payload: {
  phone: string
  role: 'admin' | 'operator'
  expected_row_version?: number
  action_id?: string
  challenge_id?: string
  code?: string
}) => request<{
  invitation_id: string
  role: 'admin' | 'operator'
  status: string
  token_generation: number
  expires_at: string
  row_version: number
  created: boolean
  rotated: boolean
  invitation_path: string
}>('/api/v1/members/invitations', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json', ...tenantCsrfHeaders() },
  body: JSON.stringify(payload),
})

export const revokeTenantInvitation = (
  invitationId: string,
  expectedRowVersion: number,
) => request<{ invitation_id: string; status: string; row_version: number }>(
  `/api/v1/members/invitations/${encodeURIComponent(invitationId)}/revoke`,
  {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...tenantCsrfHeaders() },
    body: JSON.stringify({ expected_row_version: expectedRowVersion }),
  },
)

const invitationRequest = <T>(
  path: string,
  credential: TenantInvitationCredential,
  extra: Record<string, unknown> = {},
) => request<T>(path, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ ...credential, ...extra }),
})

export const inspectTenantInvitation = (credential: TenantInvitationCredential) =>
  invitationRequest<TenantInvitationPublicSummary>(
    '/api/v1/invitations/inspect',
    credential,
  )

export const requestTenantInvitationCode = (
  credential: TenantInvitationCredential,
) => invitationRequest<TenantLoginChallenge>(
  '/api/v1/invitations/challenges',
  credential,
)

export const acceptTenantInvitation = (
  credential: TenantInvitationCredential,
  challengeId: string,
  code: string,
) => invitationRequest<{
  accepted: true
  tenant_id: string
  membership_id: string
  role: 'admin' | 'operator'
}>(
  '/api/v1/invitations/accept',
  credential,
  { challenge_id: challengeId, code },
)
