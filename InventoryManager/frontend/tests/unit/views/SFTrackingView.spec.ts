import axios from 'axios'
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import SFTrackingView from '@/views/SFTrackingView.vue'


vi.mock('axios')

const shipment = {
  shipment_id: '80000000-0000-4000-8000-000000000001',
  rental_id: 101,
  waybill_no: 'SF-TRACK-1',
  shipment_status: 'submitted',
  origin_warehouse_uuid: '20000000-0000-4000-8000-000000000001',
  submitted_at: '2026-08-23T06:00:00',
}

const tracking = {
  shipment_id: shipment.shipment_id,
  waybill_no: shipment.waybill_no,
  found: true,
  status_code: 'in_transit',
  events: [],
  last_update: null,
}

beforeEach(() => {
  vi.mocked(axios.get).mockResolvedValue({
    data: {
      success: true,
      data: { items: [shipment], next_cursor: 'next-page' },
    },
  })
  vi.mocked(axios.post).mockResolvedValue({
    data: { success: true, data: tracking },
  })
  vi.stubGlobal('alert', vi.fn())
})

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})


describe('SFTrackingView SaaS shipment contract', () => {
  it('loads one server-cursor page without legacy date or customer fields', async () => {
    const wrapper = mount(SFTrackingView)
    await flushPromises()

    expect(axios.get).toHaveBeenCalledWith('/api/sf-tracking/list', {
      params: { page_size: 20 },
    })
    expect(wrapper.text()).toContain('SF-TRACK-1')
    expect(wrapper.text()).not.toContain('客户姓名')
  })

  it('queries one immutable shipment UUID instead of a raw waybill', async () => {
    const wrapper = mount(SFTrackingView)
    await flushPromises()

    await (wrapper.vm as any).viewTracking(shipment)

    expect(axios.post).toHaveBeenCalledWith('/api/sf-tracking/query', {
      shipment_id: shipment.shipment_id,
    })
    expect(axios.post).not.toHaveBeenCalledWith(
      '/api/sf-tracking/query',
      expect.objectContaining({ tracking_number: expect.anything() }),
    )
  })

  it('batch refreshes only the current page shipment IDs', async () => {
    vi.mocked(axios.post).mockResolvedValueOnce({
      data: { success: true, data: { items: [tracking] } },
    })
    const wrapper = mount(SFTrackingView)
    await flushPromises()

    await (wrapper.vm as any).batchRefresh()

    expect(axios.post).toHaveBeenCalledWith('/api/sf-tracking/batch-query', {
      shipment_ids: [shipment.shipment_id],
    })
  })
})
