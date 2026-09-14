import type { RelayCase } from '@/types/relayCase'

type RelayEquipmentSnapshot = Pick<
  RelayCase,
  | 'lens_combo'
  | 'rental_package_id'
  | 'successor_lens_combo'
  | 'successor_rental_package_id'
  | 'accessories'
  | 'successor_accessories'
>

export function relayEquipmentWarnings(relayCase: RelayEquipmentSnapshot): string[] {
  const warnings: string[] = []
  const predecessorPackage = relayCase.rental_package_id || `legacy:${relayCase.lens_combo || ''}`
  const successorPackage = relayCase.successor_rental_package_id || `legacy:${relayCase.successor_lens_combo || ''}`
  if (predecessorPackage !== successorPackage) {
    warnings.push('租赁组合不一致')
  }
  if (relayCase.successor_accessories.length > relayCase.accessories.length) {
    warnings.push(
      `后单附件更多（${relayCase.successor_accessories.length} > ${relayCase.accessories.length}）`,
    )
  }
  return warnings
}

export function relayEquipmentWarningText(relayCase: RelayEquipmentSnapshot): string {
  return relayEquipmentWarnings(relayCase).join('；')
}
