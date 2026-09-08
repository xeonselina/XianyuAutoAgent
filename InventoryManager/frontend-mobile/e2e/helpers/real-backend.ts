import { request as playwrightRequest, type APIRequestContext } from '@playwright/test'
import path from 'node:path'
import os from 'node:os'


export const realMobileOrigin = (
  process.env.E2E_MOBILE_ORIGIN ?? 'http://127.0.0.1:5003'
)
export const realAuthStatePath = (
  process.env.E2E_AUTH_STATE_PATH
  ?? path.join(os.tmpdir(), 'xianyu-mobile-e2e-auth.json')
)

type AuthEnvelope = {
  data?: {
    csrf_token?: unknown
  }
}

export type AuthenticatedApi = {
  api: APIRequestContext
  csrfToken: string
}

export async function refreshRealCsrf(api: APIRequestContext): Promise<string> {
  const response = await api.get('/auth/me')
  if (!response.ok()) {
    throw new Error(`E2E auth bootstrap failed with HTTP ${response.status()}`)
  }
  const body = await response.json() as AuthEnvelope
  const csrfToken = body.data?.csrf_token
  if (typeof csrfToken !== 'string' || csrfToken.length === 0) {
    throw new Error('E2E auth bootstrap returned no CSRF token')
  }
  return csrfToken
}

export async function createAuthenticatedApi(): Promise<AuthenticatedApi> {
  const api = await playwrightRequest.newContext({
    baseURL: realMobileOrigin,
    storageState: realAuthStatePath,
  })
  try {
    return {
      api,
      csrfToken: await refreshRealCsrf(api),
    }
  } catch (error) {
    await api.dispose()
    throw error
  }
}

export function csrfHeaders(csrfToken: string) {
  return { 'X-CSRF-Token': csrfToken }
}
