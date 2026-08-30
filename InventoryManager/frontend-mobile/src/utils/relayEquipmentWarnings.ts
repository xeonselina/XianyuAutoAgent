import type { RelayAccessory } from '@/types/relayCase'

interface RelayEquipmentSnapshot {
  lens_combo: string | null
  rental_package_id?: string | null
  accessories: RelayAccessory[]
  successor_lens_combo: string | null
  successor_rental_package_id?: string | null
  successor_accessories: RelayAccessory[]
}

export function relayEquipmentWarningText(relayCase: RelayEquipmentSnapshot): string {
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
  return warnings.join('；')
}
