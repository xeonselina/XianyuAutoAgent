import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  beginPlatformTotpReplacement,
  beginPlatformTotpSetup,
  completePlatformTotpReplacement,
  completePlatformSetup,
  commitPlatformSubscriptionAdjustment,
  consumePlatformSetupToken,
  loginPlatformAdmin,
  getPlatformTenant,
  getPlatformTenantRentalCustomerPii,
  generatePlatformRedemptionCodeBatch,
  listPlatformRedemptionCodes,
  listPlatformTenantDevices,
  listPlatformTenantRentals,
  listPlatformTenantWarehouses,
  listPlatformTenants,
  previewPlatformSubscriptionAdjustment,
  regeneratePlatformRecoveryCodes,
  revealPlatformRedemptionCode,
  revokePlatformRedemptionCode,
  revokePlatformSession,
  stepUpPlatformSession,
} from '@/api/platformIdentity'


const response = (data: unknown, ok = true) => Promise.resolve({
  ok,
  json: () => Promise.resolve(data),
}) as Promise<Response>

describe('platformIdentity API', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    sessionStorage.clear()
  })

  it('stores only the platform login CSRF proof under its own key', async () => {
    vi.spyOn(globalThis, 'fetch').mockReturnValue(response({
      success: true,
      data: {
        csrf_token: 'platform-csrf-proof',
        session_id: 'session-1',
        role: 'platform_admin',
        mfa_method: 'totp',
      },
    }))

    await loginPlatformAdmin({
      username: 'root.admin',
      password: 'not-persisted',
      factor_method: 'totp',
      factor: '123456',
    })

    expect(sessionStorage.getItem('inventory_platform_csrf_v1'))
      .toBe('platform-csrf-proof')
    expect(sessionStorage.getItem('inventory_tenant_csrf_v1')).toBeNull()
    expect(Object.values(sessionStorage)).not.toContain('not-persisted')
    expect(Object.values(sessionStorage)).not.toContain('123456')
  })

  it('adds only the platform CSRF header to session revocation', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockReturnValue(response({
      success: true,
      data: { revoked: true, current_session_revoked: false },
    }))
    sessionStorage.setItem('inventory_platform_csrf_v1', 'platform-csrf')
    sessionStorage.setItem('inventory_tenant_csrf_v1', 'tenant-csrf')

    await revokePlatformSession('session/id')

    expect(fetchMock).toHaveBeenCalledWith(
      '/platform/api/sessions/session%2Fid/revoke',
      {
        method: 'POST',
        headers: { 'X-Platform-CSRF-Token': 'platform-csrf' },
      },
    )
  })

  it('rotates platform CSRF only after a successful recent-MFA step-up', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockReturnValue(response({
      success: true,
      data: {
        csrf_token: 'rotated-platform-csrf',
        session_id: 'replacement-session',
        role: 'platform_admin',
        mfa_method: 'totp',
        mfa_verified_at: '2026-08-22T12:00:00Z',
      },
    }))
    sessionStorage.setItem('inventory_platform_csrf_v1', 'old-platform-csrf')

    await stepUpPlatformSession({ factor_method: 'totp', factor: '123456' })

    expect(fetchMock).toHaveBeenCalledWith(
      '/platform/api/step-up',
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Platform-CSRF-Token': 'old-platform-csrf',
        },
        body: JSON.stringify({ factor_method: 'totp', factor: '123456' }),
      },
    )
    expect(sessionStorage.getItem('inventory_platform_csrf_v1'))
      .toBe('rotated-platform-csrf')
  })

  it('passes setup authority in memory from consume through TOTP completion', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch')
      .mockReturnValueOnce(response({ success: true, data: { accepted: true } }))
      .mockReturnValueOnce(response({
        success: true,
        data: { credential_id: 'credential-1', base32_seed: 'BASE32SEED' },
      }))
      .mockReturnValueOnce(response({
        success: true,
        data: { setup_completed: true, recovery_codes: ['recovery-1'] },
      }))

    await consumePlatformSetupToken('setup-secret')
    const totp = await beginPlatformTotpSetup('setup-secret')
    await completePlatformSetup(
      'setup-secret',
      totp.credential_id,
      '123456',
    )

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      '/platform/api/setup/consume',
      expect.objectContaining({ body: JSON.stringify({ setup_token: 'setup-secret' }) }),
    )
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      '/platform/api/setup/totp',
      { method: 'POST', headers: { 'X-Platform-Setup-Token': 'setup-secret' } },
    )
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      '/platform/api/setup/complete',
      expect.objectContaining({
        headers: {
          'Content-Type': 'application/json',
          'X-Platform-Setup-Token': 'setup-secret',
        },
      }),
    )
    expect(sessionStorage.length).toBe(0)
  })

  it('uses one shared CSRF boundary for factor rotation and clears it after TOTP replacement', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch')
      .mockReturnValueOnce(response({
        success: true,
        data: { recovery_code_generation: 2, recovery_codes: ['next-1'] },
      }))
      .mockReturnValueOnce(response({
        success: true,
        data: { credential_id: 'credential-2', base32_seed: 'SEED2' },
      }))
      .mockReturnValueOnce(response({
        success: true,
        data: {
          totp_generation: 2,
          recovery_code_generation: 3,
          recovery_codes: ['final-1'],
          revoked_session_count: 2,
        },
      }))
    sessionStorage.setItem('inventory_platform_csrf_v1', 'platform-csrf')

    await regeneratePlatformRecoveryCodes({
      factor_method: 'totp', factor: '111111',
    })
    const pending = await beginPlatformTotpReplacement({
      factor_method: 'recovery_code', factor: 'next-1',
    })
    await completePlatformTotpReplacement(pending.credential_id, '222222')

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      '/platform/api/factors/recovery-codes/regenerate',
      expect.objectContaining({
        headers: {
          'Content-Type': 'application/json',
          'X-Platform-CSRF-Token': 'platform-csrf',
        },
      }),
    )
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      '/platform/api/factors/totp/replacement',
      expect.any(Object),
    )
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      '/platform/api/factors/totp/replacement/complete',
      expect.objectContaining({
        body: JSON.stringify({
          credential_id: 'credential-2', totp_code: '222222',
        }),
      }),
    )
    expect(sessionStorage.getItem('inventory_platform_csrf_v1')).toBeNull()
  })

  it('encodes bounded tenant directory queries and exact detail targets', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch')
      .mockReturnValueOnce(response({
        success: true,
        data: {
          items: [], page: 2, page_size: 25, has_more: false,
          status_filter: 'suspended',
        },
      }))
      .mockReturnValueOnce(response({
        success: true,
        data: { tenant_id: 'tenant/id' },
      }))
      .mockReturnValueOnce(response({
        success: true,
        data: {
          items: [], page: 1, page_size: 25, has_more: false,
          status_filter: 'shipped',
        },
      }))
      .mockReturnValueOnce(response({
        success: true,
        data: { items: [], page: 1, page_size: 25, has_more: false },
      }))
      .mockReturnValueOnce(response({
        success: true,
        data: { items: [], page: 1, page_size: 25, has_more: false },
      }))

    await listPlatformTenants({ page: 2, page_size: 25, status: 'suspended' })
    await getPlatformTenant('tenant/id')
    const controller = new AbortController()
    await listPlatformTenantRentals(
      'tenant/id',
      { page: 1, page_size: 25, status: 'shipped' },
      controller.signal,
    )
    await listPlatformTenantDevices(
      'tenant/id',
      { page: 1, page_size: 25, lifecycle_status: 'active' },
      controller.signal,
    )
    await listPlatformTenantWarehouses(
      'tenant/id',
      { page: 1, page_size: 25, status: 'active', setup_state: 'ready' },
      controller.signal,
    )

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      '/platform/api/tenants?page=2&page_size=25&status=suspended',
      undefined,
    )
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      '/platform/api/tenants/tenant%2Fid',
      undefined,
    )
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      '/platform/api/tenants/tenant%2Fid/read/rentals'
        + '?page=1&page_size=25&status=shipped',
      { signal: controller.signal },
    )
    expect(fetchMock).toHaveBeenNthCalledWith(
      4,
      '/platform/api/tenants/tenant%2Fid/read/devices'
        + '?page=1&page_size=25&lifecycle_status=active',
      { signal: controller.signal },
    )
    expect(fetchMock).toHaveBeenNthCalledWith(
      5,
      '/platform/api/tenants/tenant%2Fid/read/warehouses'
        + '?page=1&page_size=25&status=active&setup_state=ready',
      { signal: controller.signal },
    )
  })

  it('encodes an exact PII target and never persists reason or response', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockReturnValue(response({
      success: true,
      data: {
        rental_id: 42,
        customer: {
          name: '张三',
          phone: '13800138000',
          address: {
            province: '广东省', city: '深圳市', district: null, detail: '1 号',
          },
        },
      },
    }))
    const controller = new AbortController()

    const result = await getPlatformTenantRentalCustomerPii(
      'tenant/id',
      42,
      'support:case-1',
      controller.signal,
    )

    expect(result.customer.phone).toBe('13800138000')
    expect(fetchMock).toHaveBeenCalledWith(
      '/platform/api/tenants/tenant%2Fid/read/rentals/42/customer-pii'
        + '?reason=support%3Acase-1',
      { signal: controller.signal },
    )
    expect(sessionStorage.length).toBe(0)
    expect(localStorage.length).toBe(0)
  })

  it('uses the shared platform action boundary for D53 preview and commit', async () => {
    const preview = {
      action_id: 'action-1',
      confirmation_token: 'memory-only-token',
      expected_subscription_row_version: 4,
    }
    const fetchMock = vi.spyOn(globalThis, 'fetch')
      .mockReturnValueOnce(response({ success: true, data: preview }))
      .mockReturnValueOnce(response({
        success: true,
        data: { event_id: 'event-1', created: true },
      }))
    sessionStorage.setItem('inventory_platform_csrf_v1', 'platform-csrf')
    const input = {
      operation: 'add_days' as const,
      days: 3,
      reason_code: 'customer_compensation',
      note: null,
      offline_reference: null,
      idempotency_key: 'd53:1',
    }

    await previewPlatformSubscriptionAdjustment('tenant/id', input)
    await commitPlatformSubscriptionAdjustment('tenant/id', {
      ...input,
      action_id: preview.action_id,
      expected_subscription_row_version: 4,
      confirmation_token: preview.confirmation_token,
      factor_method: 'totp',
      factor: '123456',
    })

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      '/platform/api/tenants/tenant%2Fid/subscription-adjustments/preview',
      expect.objectContaining({
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Platform-CSRF-Token': 'platform-csrf',
        },
        body: JSON.stringify(input),
      }),
    )
    const commitBody = JSON.parse(
      (fetchMock.mock.calls[1][1] as RequestInit).body as string,
    )
    expect(commitBody).not.toHaveProperty('target_expires_at')
    expect(commitBody).toMatchObject({
      confirmation_token: 'memory-only-token',
      factor: '123456',
    })
    expect(sessionStorage.getItem('memory-only-token')).toBeNull()
    expect(localStorage.length).toBe(0)
  })

  it('keeps redemption list masked and uses the shared CSRF action boundary', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch')
      .mockReturnValueOnce(response({
        success: true,
        data: { items: [], page: 1, page_size: 20, total: 0, pages: 0 },
      }))
      .mockReturnValueOnce(response({
        success: true,
        data: {
          batch_id: 'batch-1', created: true, quantity: 1,
          export_filename: 'codes.csv', export_csv: 'redemption_code\nSECRET\n',
        },
      }))
      .mockReturnValueOnce(response({
        success: true,
        data: { code_id: 'code/id', code: 'SECRET', status: 'active', row_version: 1 },
      }))
      .mockReturnValueOnce(response({
        success: true,
        data: { code_id: 'code/id', status: 'revoked', row_version: 2, changed: true },
      }))
    sessionStorage.setItem('inventory_platform_csrf_v1', 'platform-csrf')

    await listPlatformRedemptionCodes({ page: 1, page_size: 20, status: 'active' })
    await generatePlatformRedemptionCodeBatch({
      generation_request_id: 'request-1',
      name: 'batch',
      quantity: 1,
      service_duration_days: 30,
      redeem_before: '2026-12-01T00:00:00Z',
      channel: 'direct_sales',
      internal_note: 'case-1',
    })
    await revealPlatformRedemptionCode('code/id')
    await revokePlatformRedemptionCode('code/id', {
      expected_row_version: 1,
      reason_code: 'operator_revoked',
    })

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      '/platform/api/redemption-codes?page=1&page_size=20&status=active',
      undefined,
    )
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      '/platform/api/redemption-code-batches',
      expect.objectContaining({
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Platform-CSRF-Token': 'platform-csrf',
        },
      }),
    )
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      '/platform/api/redemption-codes/code%2Fid/reveal',
      expect.objectContaining({ body: '{}' }),
    )
    expect(fetchMock).toHaveBeenNthCalledWith(
      4,
      '/platform/api/redemption-codes/code%2Fid/revoke',
      expect.objectContaining({
        body: JSON.stringify({
          expected_row_version: 1,
          reason_code: 'operator_revoked',
        }),
      }),
    )
    expect(sessionStorage.getItem('SECRET')).toBeNull()
    expect(localStorage.length).toBe(0)
  })
})
