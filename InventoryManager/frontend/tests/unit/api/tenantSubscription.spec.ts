import { beforeEach, describe, expect, it, vi } from 'vitest'

import { storeTenantCsrfToken } from '@/api/tenantIdentity'
import {
  getTenantSubscriptionStatus,
  redeemTenantSubscription,
} from '@/api/tenantSubscription'


const response = (data: unknown, ok = true) => Promise.resolve({
  ok,
  json: () => Promise.resolve(data),
}) as Promise<Response>

describe('tenantSubscription API', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    sessionStorage.clear()
  })

  it('reads only the expired-page subscription projection', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockReturnValue(response({
      success: true,
      data: {
        effective_status: 'expired',
        expires_at: '2026-08-21T12:00:00Z',
        subscription_row_version: 4,
        can_redeem: true,
      },
    }))

    const status = await getTenantSubscriptionStatus()

    expect(status.subscription_row_version).toBe(4)
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/subscription/status',
      undefined,
    )
  })

  it('binds redemption to CSRF, idempotency and expected revision', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockReturnValue(response({
      success: true,
      data: {
        effective_status: 'active',
        expires_at: '2026-09-21T12:00:00Z',
        subscription_row_version: 5,
        idempotent_replay: false,
      },
    }))
    storeTenantCsrfToken('csrf-proof')

    await redeemTenantSubscription({
      code: 'CODE-VALUE',
      idempotency_key: 'renewal:request:1',
      expected_subscription_row_version: 4,
    })

    expect(fetchMock).toHaveBeenCalledWith('/api/subscription/redeem', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRF-Token': 'csrf-proof',
      },
      body: JSON.stringify({
        code: 'CODE-VALUE',
        idempotency_key: 'renewal:request:1',
        expected_subscription_row_version: 4,
      }),
    })
  })
})
