import {
  getAllowedCombos,
  getDefaultCombo,
  lensComboDisplay,
  type LensCombo,
  type LensComboConfigSource,
} from './lensCombo'

export interface RentalPackageItem {
  name: string
  qty: number
}

export interface RentalPackage {
  id?: string
  name: string
  is_active: boolean
  items: RentalPackageItem[]
}

export interface RentalPackageConfigSource extends LensComboConfigSource {
  rental_packages?: RentalPackage[] | null
  default_rental_package_id?: string | null
}

type PackageSource = RentalPackageConfigSource | string | null | undefined

const legacyId = (combo: LensCombo | string) => `legacy_${combo}`

export function getRentalPackages(source?: PackageSource): RentalPackage[] {
  if (typeof source === 'object' && source && Array.isArray(source.rental_packages) && source.rental_packages.length) {
    return source.rental_packages.map((item) => ({
      ...item,
      items: Array.isArray(item.items) ? item.items.map((entry) => ({ ...entry })) : [],
    }))
  }
  return getAllowedCombos(source).map((combo) => ({
    id: legacyId(combo),
    name: lensComboDisplay(combo),
    is_active: true,
    items: [],
  }))
}

export function getEnabledRentalPackages(source?: PackageSource): RentalPackage[] {
  return getRentalPackages(source).filter((item) => item.is_active !== false)
}

export function getDefaultRentalPackageId(source?: PackageSource): string {
  const enabled = getEnabledRentalPackages(source)
  const configured = typeof source === 'object' && source
    ? source.default_rental_package_id
    : null
  if (configured && enabled.some((item) => item.id === configured)) return configured
  const fallback = legacyId(getDefaultCombo(source))
  return enabled.some((item) => item.id === fallback) ? fallback : enabled[0]?.id || ''
}

export function isRentalPackageAllowed(source: PackageSource, packageId?: string | null): boolean {
  return Boolean(packageId && getEnabledRentalPackages(source).some((item) => item.id === packageId))
}

export function rentalPackageDisplay(
  rental: { rental_package_name?: string | null; lens_combo?: string | null } | null | undefined,
): string {
  return rental?.rental_package_name || lensComboDisplay(rental?.lens_combo)
}
