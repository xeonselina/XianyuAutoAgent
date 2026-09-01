import axios, {
  isAxiosError,
  type AxiosInstance,
  type InternalAxiosRequestConfig,
} from 'axios'


type RetriableRequest = InternalAxiosRequestConfig & {
  _tenantCsrfRecoveryAttempted?: boolean
}

type CsrfRecoveryOptions = {
  client?: AxiosInstance
  refreshToken: () => Promise<string | null>
  onInvalidSession: () => void
}

const isTenantCsrfFailure = (error: unknown) => {
  if (!isAxiosError(error) || error.response?.status !== 403) return false
  const code = (error.response.data as { code?: unknown } | undefined)?.code
  const url = error.config?.url || ''
  return code === 'CSRF_INVALID' && !url.startsWith('/platform/')
}

export const installTenantCsrfRecovery = ({
  client = axios,
  refreshToken,
  onInvalidSession,
}: CsrfRecoveryOptions) => {
  let refreshPromise: Promise<string | null> | null = null
  let invalidSessionHandled = false

  const recoverToken = () => {
    if (!refreshPromise) {
      refreshPromise = refreshToken().finally(() => {
        refreshPromise = null
      })
    }
    return refreshPromise
  }

  const handleInvalidSession = () => {
    if (invalidSessionHandled) return
    invalidSessionHandled = true
    onInvalidSession()
  }

  const interceptorId = client.interceptors.response.use(
    response => response,
    async (error: unknown) => {
      if (!isTenantCsrfFailure(error) || !isAxiosError(error)) {
        return Promise.reject(error)
      }
      const config = error.config as RetriableRequest | undefined
      if (!config || config._tenantCsrfRecoveryAttempted) {
        handleInvalidSession()
        return Promise.reject(error)
      }
      config._tenantCsrfRecoveryAttempted = true

      let token: string | null
      try {
        token = await recoverToken()
      } catch {
        handleInvalidSession()
        return Promise.reject(error)
      }
      if (!token) {
        handleInvalidSession()
        return Promise.reject(error)
      }

      config.headers.set('X-CSRF-Token', token)
      try {
        return await client.request(config)
      } catch (retryError) {
        if (isTenantCsrfFailure(retryError)) handleInvalidSession()
        return Promise.reject(retryError)
      }
    },
  )

  return () => client.interceptors.response.eject(interceptorId)
}
