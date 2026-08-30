import { describe, expect, it } from 'vitest'

import { relayEquipmentWarnings } from '@/utils/relayEquipmentWarnings'
import type { RelayCase } from '@/types/relayCase'

function relayCase(overrides: Partial<RelayCase> = {}): RelayCase {
  return {
    lens_combo: 'lens_400mm',
    successor_lens_combo: 'lens_400mm',
    accessories: [{ name: '手柄' }],
    successor_accessories: [{ name: '手柄' }],
    ...overrides,
  } as RelayCase
}

describe('relayEquipmentWarnings', () => {
  it('warns when rental packages differ', () => {
    expect(relayEquipmentWarnings(relayCase({
      successor_lens_combo: 'lens_200mm',
    }))).toEqual(['租赁组合不一致'])
  })

  it('warns when the successor has more accessories', () => {
    expect(relayEquipmentWarnings(relayCase({
      successor_accessories: [{ name: '手柄' }, { name: '备用电池' }],
    }))).toEqual(['后单附件更多（2 > 1）'])
  })

  it('compares stable package ids even when legacy lens values match', () => {
    expect(relayEquipmentWarnings(relayCase({
      rental_package_id: 'pkg_2470',
      successor_rental_package_id: 'pkg_70200',
    }))).toEqual(['租赁组合不一致'])
  })

  it('combines both reasons and stays empty for matching equipment', () => {
    expect(relayEquipmentWarnings(relayCase({
      successor_lens_combo: 'lens_200mm',
      successor_accessories: [{ name: '手柄' }, { name: '备用电池' }],
    }))).toEqual(['租赁组合不一致', '后单附件更多（2 > 1）'])
    expect(relayEquipmentWarnings(relayCase())).toEqual([])
  })
})
