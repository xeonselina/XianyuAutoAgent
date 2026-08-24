import axios, { isAxiosError } from 'axios'
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { useMobileTenantStore } from './tenant'


export type MobileSession = {
  csrf_token: string
  member: { id: number; phone: string; role: 'admin' | 'operator'; status: string }
  tenant: { id: number; name: string; access_status: string }
}

type SessionEnvelope = {
  success: boolean
  data?: MobileSession
}

export const useMobileAuthStore = defineStore('mobile-auth', () => {
  const session = ref<MobileSession | null>(null)
  const bootstrapped = ref(false)
  const authenticated = computed(() => session.value !== null)

  const clearSession = () => {
    session.value = null
    bootstrapped.value = true
    delete axios.defaults.headers.common['X-CSRF-Token']
    useMobileTenantStore().reset()
  }

  const applySession = (
    data: MobileSession,
    reloadDocument: () => void = () => window.location.reload(),
  ) => {
    if (session.value && session.value.tenant.id !== data.tenant.id) {
      clearSession()
      reloadDocument()
      return false
    }
    session.value = data
    bootstrapped.value = true
    axios.defaults.headers.common['X-CSRF-Token'] = data.csrf_token
    return true
  }

  const bootstrap = async (): Promise<boolean> => {
    if (bootstrapped.value) return authenticated.value
    try {
      const response = await axios.get<SessionEnvelope>('/auth/me')
      const data = response.data.data
      if (!data) clearSession()
      else if (!applySession(data)) return false
    } catch (error) {
      if (!isAxiosError(error) || error.response?.status !== 401) throw error
      clearSession()
    } finally {
      bootstrapped.value = true
    }
    return authenticated.value
  }

  const logoutToDesktopLogin = async (
    mobileNext: string,
    replaceDocument: (url: string) => void = (url) => window.location.replace(url),
    postLogout: typeof axios.post = axios.post,
  ) => {
    const csrf = session.value?.csrf_token
    try {
      if (csrf) {
        await postLogout(
          '/auth/logout',
          undefined,
          { headers: { 'X-CSRF-Token': csrf } },
        )
      }
    } finally {
      clearSession()
      replaceDocument(`/login?next=${encodeURIComponent(mobileNext)}`)
    }
  }

  return {
    applySession,
    authenticated,
    bootstrap,
    clearSession,
    logoutToDesktopLogin,
    session,
  }
})

type MobileTarget = { fullPath: string }

export const createMobileAuthGuard = (
  bootstrap: () => Promise<boolean>,
  assign: (url: string) => void,
  accessStatus: () => string | null | undefined = () => null,
) => async (to: MobileTarget): Promise<true | false> => {
  if (!await bootstrap()) {
    const next = `/mobile${to.fullPath}`
    assign(`/login?next=${encodeURIComponent(next)}`)
    return false
  }
  const status = accessStatus()
  if (status === 'active') return true
  const reason = status === 'expired' || status === 'suspended'
    ? status
    : 'restricted'
  assign(`/access-restricted?reason=${reason}`)
  return false
}
