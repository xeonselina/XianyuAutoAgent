import { describe, expect, it } from 'vitest'

import { compareRentalDevices as compareDesktopDevices } from '@/utils/deviceSort'
import { compareRentalDevices as compareMobileDevices } from '../../../frontend-mobile/src/utils/deviceSort'

const devices = [
  { id: 4, name: '相机10', model: 'X2', device_model: { display_name: 'X2' } },
  { id: 2, name: '相机2', model: 'X10', device_model: { display_name: 'X10' } },
  { id: 3, name: '相机2', model: 'X2', device_model: { display_name: 'X2' } },
  { id: 1, name: '相机10', model: 'X10', device_model: { display_name: 'X10' } },
]

describe('rental device option order', () => {
  it.each([
    ['PC', compareDesktopDevices],
    ['mobile', compareMobileDevices],
  ])('sorts %s choices by model, then natural device name', (_client, compare) => {
    const input = [...devices]
    expect(input.sort(compare).map(device => device.id)).toEqual([3, 4, 2, 1])
    expect(devices.map(device => device.id)).toEqual([4, 2, 3, 1])
  })
})
