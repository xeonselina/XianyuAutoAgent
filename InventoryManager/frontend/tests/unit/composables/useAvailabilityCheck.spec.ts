import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useAvailabilityCheck } from '@/composables/useAvailabilityCheck'
import type { Device } from '@/stores/gantt'

const conflictState = vi.hoisted(() => ({
  checkMultipleDevicesConflict: vi.fn(),
}))

vi.mock('@/composables/useConflictDetection', () => ({
  useConflictDetection: () => ({
    checkMultipleDevicesConflict: conflictState.checkMultipleDevicesConflict,
  }),
}))

const deferred = <T>() => {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise
  })
  return { promise, resolve }
}

const device: Device = {
  id: 11,
  name: 'VIVO X200 Ultra 01',
  serial_number: 'X200-01',
  model: 'x200u',
  model_id: 1,
  is_accessory: false,
  status: 'online',
  lifecycle_status: 'active',
  created_at: '',
  updated_at: '',
}

describe('useAvailabilityCheck request invalidation', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('does not restore device availability after reset invalidates a pending check', async () => {
    const conflicts = deferred<Record<number, boolean>>()
    conflictState.checkMultipleDevicesConflict.mockReturnValue(conflicts.promise)
    const availability = useAvailabilityCheck()

    const pendingCheck = availability.checkDevicesAvailability([device], {
      startDate: '2026-08-01',
      endDate: '2026-08-03',
      logisticsDays: 1,
    })
    availability.resetAll()
    conflicts.resolve({ 11: false })
    await pendingCheck

    expect(availability.deviceAvailability.value).toEqual({
      checked: false,
      availableItems: [],
      unavailableItems: [],
    })
  })
})
