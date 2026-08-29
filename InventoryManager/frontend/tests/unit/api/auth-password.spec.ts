import axios from 'axios'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  changeTenantPassword,
  fetchTenantAuthConfig,
  loginTenantPassword,
} from '@/api/auth'


const { axiosGet, axiosPost } = vi.hoisted(() => ({
  axiosGet: vi.fn(),
  axiosPost: vi.fn(),
}))

vi.mock('axios', () => ({
  default: {
    defaults: { headers: { common: {} } },
    get: axiosGet,
    post: axiosPost,
  },
  isAxiosError: vi.fn(() => false),
}))

const session = {
  csrf_token: 'csrf-new',
  member: {
    id: 7,
    phone: '+8613800138000',
    role: 'operator' as const,
    status: 'active' as const,
  },
  tenant: {
    id: 3,
    name: '测试租户',
    status: 'active' as const,
    provisioning_status: 'active' as const,
    expires_at: '2026-09-30T00:00:00Z',
    access_status: 'active',
  },
}

describe('tenant password auth API', () => {
  beforeEach(() => {
    vi.resetAllMocks()
  })

  it('loads only the selected public auth method', async () => {
    axiosGet.mockResolvedValue({
      data: { success: true, data: { method: 'password' } },
    })

    await expect(fetchTenantAuthConfig()).resolves.toEqual({
      method: 'password',
    })
    expect(axiosGet).toHaveBeenCalledWith('/auth/config')
  })

  it('posts phone and password to the password login endpoint', async () => {
    axiosPost.mockResolvedValue({
      data: { success: true, data: session },
    })

    await expect(
      loginTenantPassword('13800138000', 'Initial-pass-123'),
    ).resolves.toEqual(session)
    expect(axiosPost).toHaveBeenCalledWith(
      '/auth/password/login',
      { phone: '13800138000', password: 'Initial-pass-123' },
    )
  })

  it('sends password change with the current CSRF token', async () => {
    axiosPost.mockResolvedValue({ data: { success: true } })

    await changeTenantPassword(
      'Initial-pass-123',
      'Updated-pass-456',
      'csrf-current',
    )

    expect(axiosPost).toHaveBeenCalledWith(
      '/auth/password/change',
      {
        current_password: 'Initial-pass-123',
        new_password: 'Updated-pass-456',
      },
      { headers: { 'X-CSRF-Token': 'csrf-current' } },
    )
    expect(axios.defaults.headers.common).toEqual({})
  })
})
