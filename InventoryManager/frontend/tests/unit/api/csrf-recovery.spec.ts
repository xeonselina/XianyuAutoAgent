import axios, {
  AxiosError,
  AxiosHeaders,
  type AxiosAdapter,
  type AxiosResponse,
  type InternalAxiosRequestConfig,
} from 'axios'
import { describe, expect, it, vi } from 'vitest'

import { installTenantCsrfRecovery } from '@/api/csrfRecovery'


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
