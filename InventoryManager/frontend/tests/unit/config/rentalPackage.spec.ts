import { describe, expect, it } from 'vitest'

import {
  getDefaultRentalPackageId,
  getEnabledRentalPackages,
  rentalPackageDisplay,
  rentalProductLines,
} from '@/config/rentalPackage'


describe('rental package configuration', () => {
  const cameraModel = {
    rental_packages: [
      {
        id: 'pkg_2470',
        name: '机身 + 24-70',
        is_active: true,
        items: [{ name: '24-70 镜头', qty: 1 }],
      },
      {
        id: 'pkg_disabled',
        name: '停用组合',
        is_active: false,
        items: [],
      },
    ],
    default_rental_package_id: 'pkg_2470',
  }

  it('keeps arbitrary model-scoped names and hides disabled packages', () => {
    expect(getEnabledRentalPackages(cameraModel).map((item) => item.name)).toEqual([
      '机身 + 24-70',
    ])
    expect(getDefaultRentalPackageId(cameraModel)).toBe('pkg_2470')
  })

  it('uses saved rental snapshots for display and fulfillment lines', () => {
    const rental = {
      rental_package_name: '机身 + 70-200 + 增距镜',
      rental_package_items: [
        { name: '70-200 镜头', qty: 1 },
        { name: '相机电池', qty: 2 },
      ],
      lens_combo: 'bare',
    }
    expect(rentalPackageDisplay(rental)).toBe('机身 + 70-200 + 增距镜')
    expect(rentalProductLines(rental, 'camera-pro', '演唱会相机 Pro')).toEqual([
      { name: '演唱会相机 Pro', qty: 1, is_main: true },
      { name: '70-200 镜头', qty: 1, is_main: false },
      { name: '相机电池', qty: 2, is_main: false },
    ])
  })

  it('falls back to migrated legacy packages before a model is configured', () => {
    const legacyModel = {
      allowed_lens_combos: ['lens_200mm', 'bare'] as const,
      default_lens_combo: 'bare' as const,
    }
    expect(getEnabledRentalPackages(legacyModel).map((item) => item.id)).toEqual([
      'legacy_lens_200mm',
      'legacy_bare',
    ])
    expect(getDefaultRentalPackageId(legacyModel)).toBe('legacy_bare')
  })
})
