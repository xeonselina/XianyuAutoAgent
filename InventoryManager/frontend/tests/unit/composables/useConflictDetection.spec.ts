import { describe, expect, it, vi } from 'vitest'
import axios from 'axios'
import { useConflictDetection } from '@/composables/useConflictDetection'

vi.mock('axios')

describe('batch device conflict check', () => {
  it('sends one request for the device list and maps conflicting IDs', async () => {
    vi.mocked(axios.post).mockResolvedValueOnce({
      data: { success: true, data: { conflicting_device_ids: [2] } },
    })
    const { checkMultipleDevicesConflict } = useConflictDetection()
    const result = await checkMultipleDevicesConflict([1, 2, 3], {
      startDate: '2026-09-01',
      endDate: '2026-09-03',
      shipOutTime: '2026-08-30 09:00:00',
      shipInTime: '2026-09-05 18:00:00',
      excludeRentalId: 9,
    })

    expect(axios.post).toHaveBeenCalledTimes(1)
    expect(axios.post).toHaveBeenCalledWith('/api/rentals/check-device-conflicts', {
      device_ids: [1, 2, 3],
      ship_out_time: '2026-08-30 09:00:00',
      ship_in_time: '2026-09-05 18:00:00',
      exclude_rental_id: 9,
    })
    expect(result).toEqual({ 1: false, 2: true, 3: false })
  })
})
