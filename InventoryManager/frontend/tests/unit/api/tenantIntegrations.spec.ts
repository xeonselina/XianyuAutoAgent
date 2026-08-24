import { beforeEach, describe, expect, it, vi } from 'vitest'

import { storeTenantCsrfToken } from '@/api/tenantIdentity'
import {
  confirmTenantIntegrationCredentials,
  createTenantIntegration,
  listTenantIntegrations,
  requestTenantIntegrationCredentialChallenge,
  type TenantIntegrationSummary,
} from '@/api/tenantIntegrations'

const response = (data: unknown, ok = true) => Promise.resolve({
  ok,
  json: () => Promise.resolve(data),
}) as Promise<Response>

const integration: TenantIntegrationSummary = {
  integration_id: 'integration-1',
  provider: 'sf',
  name: '顺丰主连接',
  status: 'unconfigured',
  configured: false,
  last_verified_at: null,
  row_version: 3,
}

describe('tenantIntegrations API', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    sessionStorage.clear()
    storeTenantCsrfToken('tenant-csrf')
  })

  it('lists the safe integration projection', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockReturnValue(response({
      success: true,
      data: { items: [integration] },
    }))

    await expect(listTenantIntegrations()).resolves.toEqual([integration])
    expect(fetchMock).toHaveBeenCalledWith('/api/integrations', undefined)
  })

  it('preallocates create identity and sends no browser-derived credential pointer', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockReturnValue(response({
      success: true,
      data: { ...integration, idempotent: false },
    }))

    await createTenantIntegration({
      integration_id: integration.integration_id,
      provider: integration.provider,
      name: integration.name,
    })

    const init = fetchMock.mock.calls[0][1] as RequestInit
    expect(fetchMock.mock.calls[0][0]).toBe('/api/integrations')
    expect(init.headers).toEqual({
      'Content-Type': 'application/json',
      'X-CSRF-Token': 'tenant-csrf',
    })
    expect(JSON.parse(String(init.body))).toEqual({
      integration_id: 'integration-1',
      provider: 'sf',
      name: '顺丰主连接',
      config: {},
    })
  })

  it('reuses exact action facts for challenge and confirmation', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch')
      .mockReturnValueOnce(response({
        success: true,
        data: {
          intent_id: 'action-1',
          challenge_id: 'challenge-1',
          expires_at: '2026-08-23T04:00:00Z',
          replayed: false,
        },
      }))
      .mockReturnValueOnce(response({
        success: true,
        data: {
          integration_id: integration.integration_id,
          revision_id: 'revision-1',
          revision_no: 1,
          status: 'pending_validation',
          verification_status: 'not_attempted',
          validation_event_id: 'event-1',
          idempotent: false,
        },
      }))
    const credentials = { partner_id: 'partner', checkword: 'secret' }

    await requestTenantIntegrationCredentialChallenge(
      integration,
      'action-1',
      credentials,
    )
    await confirmTenantIntegrationCredentials(integration, {
      action_id: 'action-1',
      challenge_id: 'challenge-1',
      code: '123456',
      credentials,
    })

    const issued = JSON.parse(String(fetchMock.mock.calls[0][1]?.body))
    const confirmed = JSON.parse(String(fetchMock.mock.calls[1][1]?.body))
    expect(issued).toEqual({
      action_id: 'action-1',
      expected_row_version: 3,
      credentials,
    })
    expect(confirmed).toEqual({
      action_id: 'action-1',
      challenge_id: 'challenge-1',
      code: '123456',
      credentials,
      expected_row_version: 3,
    })
    expect(issued).not.toHaveProperty('expected_current_revision_id')
    expect(confirmed).not.toHaveProperty('expected_current_revision_id')
  })
})
