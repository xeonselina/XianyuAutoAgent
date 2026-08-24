import axios, { isAxiosError } from 'axios'


export type Member = {
  id: number
  phone: string
  role: 'admin' | 'operator'
  status: 'active' | 'disabled'
}

export type Tenant = {
  id: number
  name: string
  status: 'active' | 'suspended'
  provisioning_status: 'provisioning' | 'active' | 'failed'
  expires_at: string
  access_status: string
}

export type TenantSessionData = {
  csrf_token: string
  member: Member
  tenant: Tenant
}

export type PlatformSessionData = {
  csrf_token: string
  admin: { id: number; username: string }
}

export type PlatformTenant = {
  id: number
  name: string
  status: 'active' | 'suspended'
  expires_at: string
  db_name: string
  provisioning_status: 'provisioning' | 'active' | 'failed'
  provisioning_error: string | null
  admin_phone: string | null
}

type ApiEnvelope<T> = {
  success: boolean
  data?: T
  message?: string
  code?: string
}

type NewTenant = {
  name: string
  admin_phone: string
  expires_at: string
}

export type TenantPatch = Partial<Pick<NewTenant, 'name' | 'admin_phone' | 'expires_at'>> & {
  status?: 'active' | 'suspended'
  extend_days?: number
}

const responseData = <T>(envelope: ApiEnvelope<T>): T => {
  if (!envelope.success || envelope.data === undefined) {
    throw new Error(envelope.message || '请求失败')
  }
  return envelope.data
}

const csrfHeaders = (csrfToken: string) => ({
  'X-CSRF-Token': csrfToken,
})

export const setTenantCsrfHeader = (csrfToken: string | null) => {
  if (csrfToken) {
    axios.defaults.headers.common['X-CSRF-Token'] = csrfToken
  } else {
    delete axios.defaults.headers.common['X-CSRF-Token']
  }
}

export const requestTenantCode = async (phone: string): Promise<void> => {
  await axios.post('/auth/sms/request', { phone })
}

export const verifyTenantCode = async (
  phone: string,
  code: string,
): Promise<TenantSessionData> => {
  const response = await axios.post<ApiEnvelope<TenantSessionData>>(
    '/auth/sms/verify',
    { phone, code },
  )
  return responseData(response.data)
}

export const fetchTenantSession = async (): Promise<TenantSessionData> => {
  const response = await axios.get<ApiEnvelope<TenantSessionData>>('/auth/me')
  return responseData(response.data)
}

export const logoutTenantSession = async (csrfToken: string): Promise<void> => {
  await axios.post('/auth/logout', undefined, { headers: csrfHeaders(csrfToken) })
}

export const loginPlatform = async (
  username: string,
  password: string,
  totp: string,
): Promise<PlatformSessionData> => {
  const response = await axios.post<ApiEnvelope<PlatformSessionData>>(
    '/platform/auth/login',
    { username, password, totp },
  )
  return responseData(response.data)
}

export const fetchPlatformSession = async (): Promise<PlatformSessionData> => {
  const response = await axios.get<ApiEnvelope<PlatformSessionData>>(
    '/platform/auth/me',
  )
  return responseData(response.data)
}

export const logoutPlatformSession = async (csrfToken: string): Promise<void> => {
  await axios.post(
    '/platform/auth/logout',
    undefined,
    { headers: csrfHeaders(csrfToken) },
  )
}

export const listTenants = async (): Promise<PlatformTenant[]> => {
  const response = await axios.get<ApiEnvelope<PlatformTenant[]>>(
    '/platform/api/tenants',
  )
  return responseData(response.data)
}

export const createTenant = async (
  tenant: NewTenant,
  csrfToken: string,
): Promise<PlatformTenant> => {
  const response = await axios.post<ApiEnvelope<PlatformTenant>>(
    '/platform/api/tenants',
    tenant,
    { headers: csrfHeaders(csrfToken) },
  )
  return responseData(response.data)
}

export const patchTenant = async (
  tenantId: number,
  patch: TenantPatch,
  csrfToken: string,
): Promise<PlatformTenant> => {
  const response = await axios.patch<ApiEnvelope<PlatformTenant>>(
    `/platform/api/tenants/${tenantId}`,
    patch,
    { headers: csrfHeaders(csrfToken) },
  )
  return responseData(response.data)
}

export const retryTenant = async (
  tenantId: number,
  csrfToken: string,
): Promise<PlatformTenant> => {
  const response = await axios.post<ApiEnvelope<PlatformTenant>>(
    `/platform/api/tenants/${tenantId}/retry`,
    undefined,
    { headers: csrfHeaders(csrfToken) },
  )
  return responseData(response.data)
}

export const apiErrorMessage = (error: unknown): string => {
  if (isAxiosError<ApiEnvelope<unknown>>(error)) {
    return error.response?.data?.message || '请求失败，请稍后重试'
  }
  return error instanceof Error ? error.message : '请求失败，请稍后重试'
}
