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

/**
 * 将数据库中的机型名（如 'VIVO X300U 16+512'、'VIVO X300PRO 16+512'）
 * 归一化为配置 key（x200u / x300pro / x300u）。
 * 注意 x300pro 必须先于 x300u 判断，否则 "X300PRO" 会被 "x300" 误命中。
 */
export function normalizeModelName(modelName?: string | null): string | null {
  if (!modelName) return null
  if (MODEL_LENS_COMBOS[modelName]) return modelName
  const s = modelName.toLowerCase().replace(/[\s+]/g, '')
  if (s.includes('x300pro')) return 'x300pro'
  if (s.includes('x300u')) return 'x300u'
  if (s.includes('x200u')) return 'x200u'
  return null
}

export function getAllowedCombos(modelName?: string | null): LensCombo[] {
  const key = normalizeModelName(modelName)
  if (!key) return [...MODEL_LENS_COMBOS.x200u.allowed]
  const cfg = MODEL_LENS_COMBOS[key]
  return cfg ? [...cfg.allowed] : [...MODEL_LENS_COMBOS.x200u.allowed]
}

export function getDefaultCombo(modelName?: string | null): LensCombo {
  const key = normalizeModelName(modelName)
  if (!key) return 'lens_200mm'
  return MODEL_LENS_COMBOS[key]?.default ?? 'lens_200mm'
}

export function isComboAllowed(modelName: string | null | undefined, combo: LensCombo | string | null | undefined): boolean {
  const key = normalizeModelName(modelName)
  if (!key || !combo) return false
  return MODEL_LENS_COMBOS[key]?.allowed.includes(combo as LensCombo) ?? false
}

export function lensComboDisplay(combo?: LensCombo | string | null): string {
  if (!combo) return ''
  return LENS_COMBO_DISPLAY[combo as LensCombo] ?? combo
}
