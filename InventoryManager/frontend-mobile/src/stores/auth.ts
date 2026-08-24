import axios, { isAxiosError } from 'axios'
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'


type MobileSession = {
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

  const bootstrap = async (): Promise<boolean> => {
    if (bootstrapped.value) return authenticated.value
    try {
      const response = await axios.get<SessionEnvelope>('/auth/me')
      session.value = response.data.data || null
      const csrf = session.value?.csrf_token
      if (csrf) axios.defaults.headers.common['X-CSRF-Token'] = csrf
    } catch (error) {
      if (!isAxiosError(error) || error.response?.status !== 401) throw error
      session.value = null
    } finally {
      bootstrapped.value = true
    }
    return authenticated.value
  }

  return { authenticated, bootstrap, session }
})

type MobileTarget = { fullPath: string }

export const createMobileAuthGuard = (
  bootstrap: () => Promise<boolean>,
  assign: (url: string) => void,
) => async (to: MobileTarget): Promise<true | false> => {
  if (await bootstrap()) return true
  const next = `/mobile${to.fullPath}`
  assign(`/login?next=${encodeURIComponent(next)}`)
  return false
}
