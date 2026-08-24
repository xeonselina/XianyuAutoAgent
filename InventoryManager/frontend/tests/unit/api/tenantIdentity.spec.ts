import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  clearTenantCsrfToken,
  confirmTenantPhoneChange,
  confirmTenantMemberMutation,
  createTenantInvitation,
  inspectTenantInvitation,
  listTenantSessions,
  mutateTenantMember,
  revokeAllTenantSessions,
  revokeTenantSession,
  requestAdminInvitationChallenge,
  requestTenantPhoneChange,
  requestTenantLoginCode,
  requestTenantMemberMutationChallenge,
  storeTenantCsrfToken,
  verifyTenantLoginCode,
} from '@/api/tenantIdentity'


const response = (data: unknown, ok = true) => Promise.resolve({
  ok,
  json: () => Promise.resolve(data),
}) as Promise<Response>

describe('tenantIdentity API', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    sessionStorage.clear()
  })

  it('unwraps the safe per-device session list', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockReturnValue(response({
      success: true,
      data: {
        sessions: [{
          session_id: 'session-1',
          device_summary: 'Office browser',
          created_at: '2026-08-22T08:00:00Z',
          last_seen_at: '2026-08-22T09:00:00Z',
          is_current: true,
        }],
      },
    }))

    const sessions = await listTenantSessions()

    expect(sessions).toHaveLength(1)
    expect(sessions[0].device_summary).toBe('Office browser')
    expect(fetchMock).toHaveBeenCalledWith('/api/auth/sessions', undefined)
  })

  it('adds the independent CSRF proof to revocation requests', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockReturnValue(response({
      success: true,
      data: { revoked: true, current_session_revoked: false },
    }))
    storeTenantCsrfToken('csrf-proof')

    await revokeTenantSession('session/id')

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/auth/sessions/session%2Fid/revoke',
      {
        method: 'POST',
        headers: { 'X-CSRF-Token': 'csrf-proof' },
      },
    )
  })

  it('binds old and new phone codes to one action UUID', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch')
      .mockReturnValueOnce(response({
        success: true,
        data: {
          intent_id: 'action-1',
          old_challenge_id: 'old-1',
          new_challenge_id: 'new-1',
          expires_at: '2026-08-23T04:00:00Z',
          replayed: false,
        },
      }))
      .mockReturnValueOnce(response({
        success: true,
        data: { phone_changed: true, login_required: true },
      }))
    storeTenantCsrfToken('csrf-proof')

    await requestTenantPhoneChange('13900139000', 'action-1')
    await confirmTenantPhoneChange({
      new_phone: '13900139000',
      action_id: 'action-1',
      old_challenge_id: 'old-1',
      old_code: '123456',
      new_challenge_id: 'new-1',
      new_code: '654321',
    })

    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toEqual({
      new_phone: '13900139000',
      action_id: 'action-1',
    })
    expect(JSON.parse(String(fetchMock.mock.calls[1][1]?.body))).toEqual({
      new_phone: '13900139000',
      action_id: 'action-1',
      old_challenge_id: 'old-1',
      old_code: '123456',
      new_challenge_id: 'new-1',
      new_code: '654321',
    })
  })

  it('fails locally when a mutation has no login-issued CSRF proof', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch')

    await expect(revokeAllTenantSessions()).rejects.toThrow('请重新登录')
    expect(fetchMock).not.toHaveBeenCalled()

    storeTenantCsrfToken('csrf-proof')
    clearTenantCsrfToken()
    await expect(revokeAllTenantSessions()).rejects.toThrow('请重新登录')
  })

  it('keeps the challenge in memory contract and stores only login CSRF state', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch')
      .mockReturnValueOnce(response({
        success: true,
        data: {
          challenge_id: 'challenge-1',
          expires_in_seconds: 300,
          resend_after_seconds: 60,
        },
      }))
      .mockReturnValueOnce(response({
        success: true,
        data: {
          authenticated: true,
          session_id: 'session-1',
          tenant_id: 'tenant-1',
          role: 'admin',
          effective_gate: 'active',
          tenant_timezone: 'Asia/Shanghai',
          csrf_token: 'csrf-login-proof',
        },
      }))

    const challenge = await requestTenantLoginCode('13800138001')
    await verifyTenantLoginCode({
      phone: '13800138001',
      challenge_id: challenge.challenge_id,
      code: '123456',
      device_name: '桌面浏览器',
    })

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      '/api/auth/login/challenges',
      expect.objectContaining({ method: 'POST' }),
    )
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      '/api/auth/login/verify',
      expect.objectContaining({ method: 'POST' }),
    )
    expect(sessionStorage.getItem('inventory_tenant_csrf_v1'))
      .toBe('csrf-login-proof')
    expect(sessionStorage.getItem('challenge-1')).toBeNull()
  })

  it('keeps invitation credentials in request bodies and adds CSRF only to Admin mutations', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch')
      .mockReturnValueOnce(response({
        success: true,
        data: {
          invitation_id: 'invitation-1',
          role: 'operator',
          status: 'pending',
          token_generation: 1,
          expires_at: '2026-08-30T00:00:00Z',
          row_version: 1,
          created: true,
          rotated: false,
          invitation_path: '/invite#token=secret',
        },
      }))
      .mockReturnValueOnce(response({
        success: true,
        data: {
          invitation_id: 'invitation-1',
          tenant_name: '演示租户',
          role: 'operator',
          masked_phone: '+8613****8002',
          expires_at: '2026-08-30T00:00:00Z',
        },
      }))
    storeTenantCsrfToken('csrf-proof')

    await createTenantInvitation({ phone: '13900138002', role: 'operator' })
    await inspectTenantInvitation({
      invitation_id: 'invitation-1',
      token: 'secret-token',
      generation: 1,
    })

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      '/api/v1/members/invitations',
      expect.objectContaining({
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRF-Token': 'csrf-proof',
        },
      }),
    )
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      '/api/v1/invitations/inspect',
      expect.objectContaining({
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          invitation_id: 'invitation-1',
          token: 'secret-token',
          generation: 1,
        }),
      }),
    )
    expect(sessionStorage.getItem('secret-token')).toBeNull()
  })

  it('binds an Admin invitation challenge and confirmation to one action UUID', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch')
      .mockReturnValueOnce(response({
        success: true,
        data: {
          intent_id: 'action-1',
          challenge_id: 'challenge-1',
          expires_at: '2026-08-23T03:00:00Z',
          replayed: false,
        },
      }))
      .mockReturnValueOnce(response({
        success: true,
        data: {
          invitation_id: 'action-1',
          role: 'admin',
          status: 'pending',
          token_generation: 1,
          expires_at: '2026-08-30T03:00:00Z',
          row_version: 1,
          created: true,
          rotated: false,
          invitation_path: '/invite#token=secret',
        },
      }))
    storeTenantCsrfToken('csrf-proof')

    await requestAdminInvitationChallenge('13900138002', 'action-1')
    await createTenantInvitation({
      phone: '13900138002',
      role: 'admin',
      action_id: 'action-1',
      challenge_id: 'challenge-1',
      code: '123456',
    })

    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toEqual({
      phone: '13900138002',
      role: 'admin',
      action_id: 'action-1',
    })
    expect(JSON.parse(String(fetchMock.mock.calls[1][1]?.body))).toEqual({
      phone: '13900138002',
      role: 'admin',
      action_id: 'action-1',
      challenge_id: 'challenge-1',
      code: '123456',
    })
  })

  it('binds an Operator mutation to its membership revision and a UUID action', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockReturnValue(response({
      success: true,
      data: {
        membership_id: 'member/1',
        role: 'operator',
        status: 'disabled',
        row_version: 4,
        sessions_revoked: 1,
        idempotent: false,
      },
    }))
    storeTenantCsrfToken('csrf-proof')

    await mutateTenantMember({
      membership_id: 'member/1',
      role: 'operator',
      status: 'active',
      masked_phone: '+8613****8002',
      row_version: 3,
    }, 'disable')

    const [, init] = fetchMock.mock.calls[0]
    expect(fetchMock.mock.calls[0][0]).toBe(
      '/api/v1/members/member%2F1/mutations',
    )
    expect(init?.headers).toEqual({
      'Content-Type': 'application/json',
      'X-CSRF-Token': 'csrf-proof',
    })
    expect(JSON.parse(String(init?.body))).toEqual({
      action: 'disable',
      action_id: expect.stringMatching(
        /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/,
      ),
      expected_row_version: 3,
    })
  })

  it('reuses one action UUID across Admin challenge and confirmation', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch')
      .mockReturnValueOnce(response({
        success: true,
        data: {
          intent_id: '11111111-1111-4111-8111-111111111111',
          challenge_id: '22222222-2222-4222-8222-222222222222',
          expires_at: '2026-08-23T02:10:00Z',
          replayed: false,
        },
      }))
      .mockReturnValueOnce(response({
        success: true,
        data: {
          membership_id: 'member/1',
          role: 'admin',
          status: 'active',
          row_version: 4,
          sessions_revoked: 1,
          idempotent: false,
        },
      }))
    storeTenantCsrfToken('csrf-proof')
    const member = {
      membership_id: 'member/1',
      role: 'operator' as const,
      status: 'active' as const,
      masked_phone: '+8613****8002',
      row_version: 3,
    }
    const actionId = '11111111-1111-4111-8111-111111111111'

    const challenge = await requestTenantMemberMutationChallenge(
      member,
      'change_role',
      actionId,
      'admin',
    )
    await confirmTenantMemberMutation(
      member,
      'change_role',
      actionId,
      challenge.challenge_id,
      '123456',
      'admin',
    )

    expect(fetchMock.mock.calls[0][0]).toBe(
      '/api/v1/members/member%2F1/mutations/challenge',
    )
    expect(fetchMock.mock.calls[1][0]).toBe(
      '/api/v1/members/member%2F1/mutations/confirm',
    )
    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toEqual({
      action: 'change_role',
      action_id: actionId,
      expected_row_version: 3,
      target_role: 'admin',
    })
    expect(JSON.parse(String(fetchMock.mock.calls[1][1]?.body))).toEqual({
      action: 'change_role',
      action_id: actionId,
      expected_row_version: 3,
      target_role: 'admin',
      challenge_id: '22222222-2222-4222-8222-222222222222',
      code: '123456',
    })
  })
})
