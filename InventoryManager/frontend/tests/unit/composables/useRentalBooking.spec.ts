import axios from 'axios'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  useRentalBooking,
  type BookingAvailabilityPayload,
} from '@/composables/useRentalBooking'

const deferred = <T>() => {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise
  })
  return { promise, resolve }
}

const payload = (modelId: number): BookingAvailabilityPayload => ({
  start_date: '2026-09-01',
  end_date: '2026-09-03',
  model_id: modelId,
  preferred_warehouse_id: 1,
  destination: {
    province: '广东省',
    city: '深圳市',
    district: '南山区',
    address_detail: '测试路1号',
  },
  requested_accessory_type_ids: [],
})

describe('useRentalBooking', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('deduplicates one in-flight bootstrap request', async () => {
    const pending = deferred<any>()
    const get = vi.spyOn(axios, 'get').mockReturnValue(pending.promise)
    const booking = useRentalBooking()

    const first = booking.loadBootstrap()
    const second = booking.loadBootstrap()
    pending.resolve({
      data: {
        data: {
          request_id: 'bootstrap-1',
          evaluated_at: '2026-08-22T00:00:00Z',
          warehouses: [],
          recent_warehouse_id: null,
          default_warehouse_id: null,
          device_models: [],
          accessory_types: [],
          form_policy: {},
        },
      },
    })

    await expect(first).resolves.toMatchObject({ request_id: 'bootstrap-1' })
    await expect(second).resolves.toMatchObject({ request_id: 'bootstrap-1' })
    expect(get).toHaveBeenCalledTimes(1)
  })

  it('does not let a stale availability response overwrite newer filters', async () => {
    const older = deferred<any>()
    const newer = deferred<any>()
    vi.spyOn(axios, 'post')
      .mockReturnValueOnce(older.promise)
      .mockReturnValueOnce(newer.promise)
    const booking = useRentalBooking()

    const first = booking.evaluateAvailability(payload(1))
    const second = booking.evaluateAvailability(payload(2))
    newer.resolve({
      data: { data: { request_id: 'newer', candidates: [] } },
    })
    await expect(second).resolves.toMatchObject({ request_id: 'newer' })
    older.resolve({
      data: { data: { request_id: 'older', candidates: [] } },
    })
    await expect(first).resolves.toBeNull()

    expect(booking.availability.value?.request_id).toBe('newer')
    expect(axios.post).toHaveBeenCalledTimes(2)
  })

  it('fails closed when the current availability request fails', async () => {
    vi.spyOn(axios, 'post').mockRejectedValue(new Error('timeout'))
    const booking = useRentalBooking()

    await expect(
      booking.evaluateAvailability(payload(1)),
    ).rejects.toThrow('timeout')
    expect(booking.availability.value).toBeNull()
    expect(booking.availabilityFailed.value).toBe(true)
  })
})
