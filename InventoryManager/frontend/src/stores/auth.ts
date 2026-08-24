import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { isAxiosError } from 'axios'

import {
  fetchPlatformSession,
  fetchTenantSession,
  loginPlatform,
  logoutPlatformSession,
  logoutTenantSession,
  requestTenantCode,
  setTenantCsrfHeader,
  verifyTenantCode,
  type Member,
  type PlatformSessionData,
  type Tenant,
  type TenantSessionData,
} from '@/api/auth'
import { useTenantStore } from '@/stores/tenant'


export const useAuthStore = defineStore('auth', () => {
  const member = ref<Member | null>(null)
  const tenant = ref<Tenant | null>(null)
  const csrfToken = ref<string | null>(null)
  const tenantBootstrapped = ref(false)

  const platformAdmin = ref<PlatformSessionData['admin'] | null>(null)
  const platformCsrfToken = ref<string | null>(null)
  const platformBootstrapped = ref(false)

  const authenticated = computed(() => member.value !== null && tenant.value !== null)
  const platformAuthenticated = computed(() => platformAdmin.value !== null)
  const accessStatus = computed(() => tenant.value?.access_status || null)

  const applyTenantSession = (
    data: TenantSessionData,
    reloadDocument: () => void = () => window.location.reload(),
  ) => {
    if (tenant.value && tenant.value.id !== data.tenant.id) {
      clearTenantSession()
      reloadDocument()
      return false
    }
    member.value = data.member
    tenant.value = data.tenant
    csrfToken.value = data.csrf_token
    tenantBootstrapped.value = true
    setTenantCsrfHeader(data.csrf_token)
    return true
  }

  const clearTenantSession = () => {
    member.value = null
    tenant.value = null
    csrfToken.value = null
    tenantBootstrapped.value = true
    setTenantCsrfHeader(null)
    useTenantStore().reset()
  }

  const bootstrap = async (): Promise<boolean> => {
    if (tenantBootstrapped.value) return authenticated.value
    try {
      if (!applyTenantSession(await fetchTenantSession())) return false
    } catch (error) {
      if (!isAxiosError(error) || error.response?.status !== 401) throw error
      clearTenantSession()
    }
    return authenticated.value
  }

  const requestCode = async (phone: string) => requestTenantCode(phone)

  const verifyCode = async (phone: string, code: string) => {
    return applyTenantSession(await verifyTenantCode(phone, code))
  }

  const logout = async () => {
    try {
      if (csrfToken.value) await logoutTenantSession(csrfToken.value)
    } finally {
      clearTenantSession()
    }
  }

  const logoutTo = async (
    destination: string,
    replaceDocument: (url: string) => void = (url) => window.location.replace(url),
  ) => {
    try {
      await logout()
    } finally {
      replaceDocument(destination)
    }
  }

  const applyPlatformSession = (data: PlatformSessionData) => {
    platformAdmin.value = data.admin
    platformCsrfToken.value = data.csrf_token
    platformBootstrapped.value = true
  }

  const clearPlatformSession = () => {
    platformAdmin.value = null
    platformCsrfToken.value = null
    platformBootstrapped.value = true
  }

  const bootstrapPlatform = async (): Promise<boolean> => {
    if (platformBootstrapped.value) return platformAuthenticated.value
    try {
      applyPlatformSession(await fetchPlatformSession())
    } catch (error) {
      if (!isAxiosError(error) || error.response?.status !== 401) throw error
      clearPlatformSession()
    }
    return platformAuthenticated.value
  }

  const verifyPlatform = async (username: string, password: string, totp: string) => {
    applyPlatformSession(await loginPlatform(username, password, totp))
  }

  const logoutPlatform = async () => {
    if (platformCsrfToken.value) {
      await logoutPlatformSession(platformCsrfToken.value)
    }
    clearPlatformSession()
  }

  return {
    accessStatus,
    applyPlatformSession,
    applyTenantSession,
    authenticated,
    bootstrap,
    bootstrapPlatform,
    csrfToken,
    logout,
    logoutTo,
    logoutPlatform,
    member,
    platformAdmin,
    platformAuthenticated,
    platformCsrfToken,
    requestCode,
    tenant,
    verifyCode,
    verifyPlatform,
  }
})
