import type { RelayCase } from '@/types/relayCase'

export function relayEquipmentWarningText(relayCase: RelayCase): string {
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
