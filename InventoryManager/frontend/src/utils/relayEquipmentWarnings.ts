import type { RelayCase } from '@/types/relayCase'

type RelayEquipmentSnapshot = Pick<
  RelayCase,
  | 'lens_combo'
  | 'successor_lens_combo'
  | 'accessories'
  | 'successor_accessories'
>

export function relayEquipmentWarnings(relayCase: RelayEquipmentSnapshot): string[] {
  const warnings: string[] = []
  if (relayCase.lens_combo !== relayCase.successor_lens_combo) {
    warnings.push('镜头组合不一致')
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
