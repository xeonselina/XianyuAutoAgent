import axios from 'axios'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  createManualRelayCase,
  listRelayCases,
  listManualRelayOptions,
  refreshRelayTracking,
  refreshRelayTrackingBatch,
  updateRelayCase,
} from '@/api/relayCases'


vi.mock('axios', () => ({
  default: {
    get: vi.fn(),
    put: vi.fn(),
    post: vi.fn(),
  },
}))


describe('relayCases API', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('serializes status multi-select and ship date range', async () => {
    vi.mocked(axios.get).mockResolvedValue({
      data: { success: true, data: { items: [], total: 0 } },
    })

    await listRelayCases({
      statuses: ['pending', 'notified'],
      shipDateFrom: '2026-08-02',
      shipDateTo: '2026-08-10',
      page: 2,
      perPage: 50,
    })

    expect(axios.get).toHaveBeenCalledWith('/api/relay-cases', {
      params: {
        statuses: 'pending,notified',
        ship_date_from: '2026-08-02',
        ship_date_to: '2026-08-10',
        page: 2,
        per_page: 50,
      },
    })
  })

  it('uses pair and case endpoints for mutations', async () => {
    vi.mocked(axios.put).mockResolvedValue({
      data: { success: true, data: { status: 'notified' } },
    })
    vi.mocked(axios.post).mockResolvedValue({
      data: { success: true, data: {} },
    })

    await updateRelayCase(1, 2, {
      status: 'notified',
      sf_tracking_number: undefined,
    })
    await refreshRelayTracking(7)
    await refreshRelayTrackingBatch([7, 8])
    await listManualRelayOptions()
    await createManualRelayCase(11)

    expect(axios.put).toHaveBeenCalledWith('/api/relay-cases/1/2', {
      status: 'notified',
      sf_tracking_number: undefined,
    })
    expect(axios.post).toHaveBeenCalledWith(
      '/api/relay-cases/7/tracking/refresh',
    )
    expect(axios.post).toHaveBeenCalledWith(
      '/api/relay-cases/tracking/refresh-batch',
      { case_ids: [7, 8] },
    )
    expect(axios.get).toHaveBeenCalledWith(
      '/api/relay-cases/manual-options',
    )
    expect(axios.post).toHaveBeenCalledWith(
      '/api/relay-cases/manual',
      { device_id: 11 },
    )
  })

  it('surfaces the backend business message from a failed mutation', async () => {
    vi.mocked(axios.put).mockRejectedValue({
      response: {
        status: 409,
        data: { success: false, message: '目标订单已存在其他接力绑定' },
      },
    })

    let caught: unknown
    try {
      await updateRelayCase(1, 2, { status: 'agreed' })
    } catch (error) {
      caught = error
    }

    expect(caught).toBeInstanceOf(Error)
    expect((caught as Error).message).toBe('目标订单已存在其他接力绑定')
  })
})
