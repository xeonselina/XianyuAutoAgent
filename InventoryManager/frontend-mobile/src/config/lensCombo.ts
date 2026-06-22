/**
 * 镜头组合配置 - 与后端 app/services/printing/rental_product_lines.py 保持一致
 * 移动端共享 PC 端定义，逻辑完全一致。
 */

export type LensCombo = 'lens_400mm' | 'lens_200mm' | 'bare' | 'lens_dual'

export interface LensComboModelConfig {
  allowed: LensCombo[]
  default: LensCombo
}

export const MODEL_LENS_COMBOS: Record<string, LensComboModelConfig> = {
  x200u:   { allowed: ['lens_200mm', 'bare'],                              default: 'lens_200mm' },
  x300pro: { allowed: ['lens_200mm', 'bare'],                              default: 'lens_200mm' },
  x300u:   { allowed: ['lens_400mm', 'lens_200mm', 'bare', 'lens_dual'],   default: 'lens_400mm' },
}

export const LENS_COMBO_DISPLAY: Record<LensCombo, string> = {
  lens_400mm: '400MM 镜头',
  lens_200mm: '200MM 镜头',
  bare:       '裸机',
  lens_dual:  '双镜头',
}

export function getAllowedCombos(modelName?: string | null): LensCombo[] {
  if (!modelName) return [...MODEL_LENS_COMBOS.x200u.allowed]
  const cfg = MODEL_LENS_COMBOS[modelName]
  return cfg ? [...cfg.allowed] : [...MODEL_LENS_COMBOS.x200u.allowed]
}

export function getDefaultCombo(modelName?: string | null): LensCombo {
  if (!modelName) return 'lens_200mm'
  return MODEL_LENS_COMBOS[modelName]?.default ?? 'lens_200mm'
}

export function isComboAllowed(modelName: string | null | undefined, combo: LensCombo | string | null | undefined): boolean {
  if (!modelName || !combo) return false
  return MODEL_LENS_COMBOS[modelName]?.allowed.includes(combo as LensCombo) ?? false
}

export function lensComboDisplay(combo?: LensCombo | string | null): string {
  if (!combo) return ''
  return LENS_COMBO_DISPLAY[combo as LensCombo] ?? combo
}
