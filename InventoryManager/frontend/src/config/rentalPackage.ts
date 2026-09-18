import {
  getAllowedCombos,
  getDefaultCombo,
  getProductLines,
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
  client_id?: string
  name: string
  is_active: boolean
  items: RentalPackageItem[]
}

export interface RentalPackageConfigSource extends LensComboConfigSource {
  rental_packages?: RentalPackage[] | null
  default_rental_package_id?: string | null
}

export const legacyRentalPackageId = (combo: LensCombo | string) => `legacy_${combo}`

const legacyPackage = (combo: LensCombo): RentalPackage => ({
  id: legacyRentalPackageId(combo),
  name: lensComboDisplay(combo),
  is_active: true,
  items: getProductLines(null, combo).slice(1).map(({ name, qty }) => ({ name, qty })),
})

export function getRentalPackages(source?: RentalPackageConfigSource | null): RentalPackage[] {
  const configured = source?.rental_packages
  if (Array.isArray(configured) && configured.length) {
    return configured.map((item) => ({
      ...item,
      items: Array.isArray(item.items) ? item.items.map((entry) => ({ ...entry })) : [],
    }))
  }
  return getAllowedCombos(source).map(legacyPackage)
}

export function getEnabledRentalPackages(source?: RentalPackageConfigSource | null): RentalPackage[] {
  return getRentalPackages(source).filter((item) => item.is_active !== false)
}

export function getDefaultRentalPackageId(source?: RentalPackageConfigSource | null): string {
  const enabled = getEnabledRentalPackages(source)
  const configured = source?.default_rental_package_id
  if (configured && enabled.some((item) => item.id === configured)) return configured
  const legacyDefault = legacyRentalPackageId(getDefaultCombo(source))
  if (enabled.some((item) => item.id === legacyDefault)) return legacyDefault
  return enabled[0]?.id || ''
}

export function isRentalPackageAllowed(
  source: RentalPackageConfigSource | null | undefined,
  packageId: string | null | undefined,
): boolean {
  return Boolean(packageId && getEnabledRentalPackages(source).some((item) => item.id === packageId))
}

export function rentalPackageDisplay(
  rental: { rental_package_name?: string | null; lens_combo?: string | null } | null | undefined,
): string {
  return rental?.rental_package_name || lensComboDisplay(rental?.lens_combo)
}

export function rentalProductLines(
  rental: {
    rental_package_items?: RentalPackageItem[] | null
    lens_combo?: string | null
  } | null | undefined,
  modelName?: string | null,
  displayName?: string | null,
) {
  const snapshotItems = rental?.rental_package_items
  if (Array.isArray(snapshotItems)) {
    return [
      { name: displayName || modelName || '主机', qty: 1, is_main: true },
      ...snapshotItems.map((item) => ({ ...item, is_main: false })),
    ]
  }
  return getProductLines(modelName, rental?.lens_combo, displayName)
}
