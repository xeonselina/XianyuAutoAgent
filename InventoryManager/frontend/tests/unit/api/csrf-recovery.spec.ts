import axios, {
  AxiosError,
  AxiosHeaders,
  type AxiosAdapter,
  type AxiosResponse,
  type InternalAxiosRequestConfig,
} from 'axios'
import { describe, expect, it, vi } from 'vitest'

import { installTenantCsrfRecovery } from '@/api/csrfRecovery'
import { installTenantCsrfRecovery as installMobileTenantCsrfRecovery } from '../../../../frontend-mobile/src/api/csrfRecovery'


const response = (
  config: InternalAxiosRequestConfig,
  status: number,
  data: unknown,
): AxiosResponse => ({
  config,
  data,
  headers: {},
  status,
  statusText: status === 200 ? 'OK' : 'Forbidden',
})

const csrfError = (config: InternalAxiosRequestConfig) => new AxiosError(
  'forbidden',
  AxiosError.ERR_BAD_REQUEST,
  config,
  undefined,
  response(config, 403, { code: 'CSRF_INVALID' }),
)

const authError = (
  config: InternalAxiosRequestConfig,
  code = 'AUTH_REQUIRED',
) => new AxiosError(
  'unauthorized',
  AxiosError.ERR_BAD_REQUEST,
  config,
  undefined,
  response(config, 401, { code }),
)

describe('tenant CSRF recovery', () => {
  it('refreshes once and retries concurrent failed writes with the new token', async () => {
    const client = axios.create()
    const requests: InternalAxiosRequestConfig[] = []
    const adapter: AxiosAdapter = async (config) => {
      requests.push(config)
      if (config.headers.get('X-CSRF-Token') !== 'csrf-current') {
        throw csrfError(config)
      }
      return response(config, 200, { success: true })
    }
    client.defaults.adapter = adapter
    client.defaults.headers.common['X-CSRF-Token'] = 'csrf-stale'
    const refreshToken = vi.fn(async () => {
      await Promise.resolve()
      return 'csrf-current'
    })
    const onInvalidSession = vi.fn()
    const uninstall = installTenantCsrfRecovery({
      client,
      refreshToken,
      onInvalidSession,
    })

    const results = await Promise.all([
      client.post('/api/first'),
      client.put('/web/second'),
    ])

    expect(results.map(result => result.status)).toEqual([200, 200])
    expect(refreshToken).toHaveBeenCalledTimes(1)
    expect(onInvalidSession).not.toHaveBeenCalled()
    expect(requests).toHaveLength(4)
    expect(requests.slice(2).map(request => (
      request.headers.get('X-CSRF-Token')
    ))).toEqual(['csrf-current', 'csrf-current'])
    uninstall()
  })

  it('invalidates the session when refresh cannot recover a token', async () => {
    const client = axios.create()
    client.defaults.adapter = (async (config) => {
      throw csrfError(config)
    }) as AxiosAdapter
    const onInvalidSession = vi.fn()
    installTenantCsrfRecovery({
      client,
      refreshToken: async () => null,
      onInvalidSession,
    })

    await expect(client.post('/api/write')).rejects.toMatchObject({
      response: { status: 403 },
    })
    expect(onInvalidSession).toHaveBeenCalledTimes(1)
  })

  it('does not treat platform CSRF failures as tenant sessions', async () => {
    const client = axios.create()
    client.defaults.adapter = (async (config) => {
      config.headers = AxiosHeaders.from(config.headers)
      throw csrfError(config)
    }) as AxiosAdapter
    const refreshToken = vi.fn(async () => 'tenant-token')
    const onInvalidSession = vi.fn()
    installTenantCsrfRecovery({
      client,
      refreshToken,
      onInvalidSession,
    })

    await expect(client.patch('/platform/tenants/1')).rejects.toBeInstanceOf(
      AxiosError,
    )
    expect(refreshToken).not.toHaveBeenCalled()
    expect(onInvalidSession).not.toHaveBeenCalled()
  })
})

describe('expired sessions during API requests', () => {
  it('redirects once when concurrent tenant requests return AUTH_REQUIRED', async () => {
    const client = axios.create()
    client.defaults.adapter = (async (config) => {
      throw authError(config)
    }) as AxiosAdapter
    const onInvalidSession = vi.fn()
    const onInvalidPlatformSession = vi.fn()
    installTenantCsrfRecovery({
      client,
      refreshToken: async () => null,
      onInvalidSession,
      onInvalidPlatformSession,
    })

    await Promise.allSettled([
      client.get('/api/gantt/data'),
      client.post('/api/rentals'),
    ])

    expect(onInvalidSession).toHaveBeenCalledOnce()
    expect(onInvalidPlatformSession).not.toHaveBeenCalled()
  })

  it('handles 401 responses accepted by validateStatus', async () => {
    const client = axios.create()
    client.defaults.adapter = (async (config) => response(
      config,
      401,
      { code: 'AUTH_REQUIRED' },
    )) as AxiosAdapter
    const onInvalidSession = vi.fn()
    installTenantCsrfRecovery({
      client,
      refreshToken: async () => null,
      onInvalidSession,
    })

    const result = await client.put('/api/inspections/3', {}, {
      validateStatus: () => true,
    })

    expect(result.status).toBe(401)
    expect(onInvalidSession).toHaveBeenCalledOnce()
  })

  it('keeps invalid credentials on the login form and sends expired platform sessions to platform login', async () => {
    const client = axios.create()
    client.defaults.adapter = (async (config) => {
      throw authError(
        config,
        config.url === '/auth/password/login' ? 'AUTH_INVALID' : 'AUTH_REQUIRED',
      )
    }) as AxiosAdapter
    const onInvalidSession = vi.fn()
    const onInvalidPlatformSession = vi.fn()
    installTenantCsrfRecovery({
      client,
      refreshToken: async () => null,
      onInvalidSession,
      onInvalidPlatformSession,
    })

    await expect(client.post('/auth/password/login')).rejects.toBeInstanceOf(AxiosError)
    expect(onInvalidSession).not.toHaveBeenCalled()
    await expect(client.get('/platform/api/tenants')).rejects.toBeInstanceOf(AxiosError)
    expect(onInvalidPlatformSession).toHaveBeenCalledOnce()
    expect(onInvalidSession).not.toHaveBeenCalled()
  })

  it('redirects mobile tenant requests when the session expires', async () => {
    const client = axios.create()
    client.defaults.adapter = (async (config) => {
      throw authError(config)
    }) as AxiosAdapter
    const onInvalidSession = vi.fn()
    installMobileTenantCsrfRecovery({
      client,
      refreshToken: async () => null,
      onInvalidSession,
    })

    await expect(client.post('/api/rentals')).rejects.toBeInstanceOf(AxiosError)
    expect(onInvalidSession).toHaveBeenCalledOnce()
  })
})
