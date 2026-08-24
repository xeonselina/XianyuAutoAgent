import ElementPlus, { ElMessage, ElMessageBox } from 'element-plus'
import { flushPromises, shallowMount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import PlatformRedemptionCodesView from '@/views/PlatformRedemptionCodesView.vue'


const api = vi.hoisted(() => ({
  generatePlatformRedemptionCodeBatch: vi.fn(),
  listPlatformRedemptionCodes: vi.fn(),
  revealPlatformRedemptionCode: vi.fn(),
  revokePlatformRedemptionCode: vi.fn(),
}))
const router = vi.hoisted(() => ({ push: vi.fn() }))

vi.mock('@/api/platformIdentity', () => api)
vi.mock('vue-router', () => ({ useRouter: () => router }))

const item = {
  code_id: 'code-1',
  batch_id: 'batch-1',
  batch_name: 'Core batch',
  channel: 'direct_sales',
  internal_note: null,
  masked_code: 'ABCD-****-****-****-****-****-**',
  status: 'active',
  row_version: 1,
  plan_revision_id: 'plan-1',
  service_duration_seconds: 2_592_000,
  redeem_before: '2026-12-01T00:00:00Z',
  created_at: '2026-08-23T00:00:00Z',
  reserved_attempt_id: null,
  reserved_attempt_status: null,
  redeemed_tenant_id: null,
  redeemed_user_id: null,
  redeemed_at: null,
  revocation_reason_code: null,
}

describe('PlatformRedemptionCodesView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    sessionStorage.clear()
    localStorage.clear()
    vi.spyOn(globalThis.crypto, 'randomUUID')
      .mockReturnValue('11111111-1111-4111-8111-111111111111')
    api.listPlatformRedemptionCodes.mockResolvedValue({
      items: [item], page: 1, page_size: 20, total: 1, pages: 1,
    })
    api.revealPlatformRedemptionCode.mockResolvedValue({
      code_id: item.code_id,
      code: '0123456789ABCDEFGHJKMNPQRS',
      status: 'active',
      row_version: 1,
    })
    api.revokePlatformRedemptionCode.mockResolvedValue({
      code_id: item.code_id, status: 'revoked', row_version: 2, changed: true,
    })
    vi.spyOn(ElMessage, 'success').mockImplementation(() => undefined as never)
    vi.spyOn(ElMessage, 'info').mockImplementation(() => undefined as never)
    vi.spyOn(ElMessage, 'error').mockImplementation(() => undefined as never)
    vi.spyOn(ElMessage, 'warning').mockImplementation(() => undefined as never)
    vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue('confirm')
  })

  afterEach(() => vi.restoreAllMocks())

  const mountView = () => shallowMount(PlatformRedemptionCodesView, {
    global: {
      plugins: [ElementPlus],
      directives: { loading: () => undefined },
    },
  })

  it('loads only masked rows and clears each revealed bearer on close and unmount', async () => {
    const wrapper = mountView()
    await flushPromises()
    const state = wrapper.vm.$.setupState

    expect(api.listPlatformRedemptionCodes).toHaveBeenCalledWith({
      page: 1, page_size: 20,
    })
    expect(state.items).toEqual([item])
    expect(JSON.stringify(state.items)).not.toContain(
      '0123456789ABCDEFGHJKMNPQRS',
    )

    await state.reveal(item)
    expect(state.revealedCode).toBe('0123456789ABCDEFGHJKMNPQRS')
    state.clearReveal()
    expect(state.revealedCode).toBe('')
    await state.reveal(item)
    wrapper.unmount()
    expect(state.revealedCode).toBe('')
    expect(sessionStorage.length).toBe(0)
    expect(localStorage.length).toBe(0)
  })

  it('downloads only the successful initial response without browser persistence', async () => {
    const wrapper = mountView()
    await flushPromises()
    const state = wrapper.vm.$.setupState
    const createObjectURL = vi.fn(() => 'blob:codes')
    const revokeObjectURL = vi.fn()
    const originalCreateObjectURL = URL.createObjectURL
    const originalRevokeObjectURL = URL.revokeObjectURL
    URL.createObjectURL = createObjectURL
    URL.revokeObjectURL = revokeObjectURL
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click')
      .mockImplementation(() => undefined)
    api.generatePlatformRedemptionCodeBatch.mockResolvedValue({
      batch_id: 'batch-1',
      created: true,
      quantity: 1,
      export_filename: 'codes.csv',
      export_csv: 'redemption_code\nSECRET\n',
    })
    state.redeemBefore = new Date('2026-12-01T00:00:00Z')

    await state.generate()

    expect(api.generatePlatformRedemptionCodeBatch).toHaveBeenCalledWith({
      generation_request_id: '11111111-1111-4111-8111-111111111111',
      name: 'Core 兑换码',
      quantity: 1,
      service_duration_days: 365,
      redeem_before: '2026-12-01T00:00:00.000Z',
      channel: 'direct_sales',
      internal_note: null,
    })
    expect(createObjectURL).toHaveBeenCalledTimes(1)
    expect(click).toHaveBeenCalledTimes(1)
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:codes')
    expect(sessionStorage.length).toBe(0)
    expect(localStorage.length).toBe(0)
    wrapper.unmount()
    URL.createObjectURL = originalCreateObjectURL
    URL.revokeObjectURL = originalRevokeObjectURL
  })

  it('revokes only the current active row version and reloads', async () => {
    const wrapper = mountView()
    await flushPromises()
    const state = wrapper.vm.$.setupState

    await state.revoke(item)

    expect(api.revokePlatformRedemptionCode).toHaveBeenCalledWith(
      'code-1',
      { expected_row_version: 1, reason_code: 'operator_revoked' },
    )
    expect(api.listPlatformRedemptionCodes).toHaveBeenCalledTimes(2)
    wrapper.unmount()
  })
})
