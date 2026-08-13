import type { RelayAccessory } from '@/types/relayCase'

interface RelayEquipmentSnapshot {
  lens_combo: string | null
  accessories: RelayAccessory[]
  successor_lens_combo: string | null
  successor_accessories: RelayAccessory[]
}

export function relayEquipmentWarningText(relayCase: RelayEquipmentSnapshot): string {
  const warnings: string[] = []
  if (relayCase.lens_combo !== relayCase.successor_lens_combo) {
    warnings.push('镜头组合不一致')
  }
  if (relayCase.successor_accessories.length > relayCase.accessories.length) {
    warnings.push(
      `后单附件更多（${relayCase.successor_accessories.length} > ${relayCase.accessories.length}）`,
    )
  }
  return warnings.join('；')
}
