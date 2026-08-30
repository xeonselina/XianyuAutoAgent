/**
 * 镜头组合的稳定枚举和展示规则；型号可选项由型号库接口提供。
 */

export type LensCombo = 'lens_400mm' | 'lens_200mm' | 'bare' | 'lens_dual'

export interface LensComboConfigSource {
  name?: string | null
  allowed_lens_combos?: LensCombo[] | null
  default_lens_combo?: LensCombo | null
}

export const LENS_COMBO_VALUES: LensCombo[] = ['lens_400mm', 'lens_200mm', 'bare', 'lens_dual']
const FALLBACK_ALLOWED: LensCombo[] = ['lens_200mm', 'bare']

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
  const s = modelName.toLowerCase().replace(/[\s+]/g, '')
  if (s.includes('x300pro')) return 'x300pro'
  if (s.includes('x300u')) return 'x300u'
  if (s.includes('x200u')) return 'x200u'
  return null
}

function compatibilityConfig(modelName?: string | null): { allowed: LensCombo[]; default: LensCombo } {
  if (normalizeModelName(modelName) === 'x300u') {
    return { allowed: [...LENS_COMBO_VALUES], default: 'lens_400mm' }
  }
  return { allowed: [...FALLBACK_ALLOWED], default: 'lens_200mm' }
}

function resolveConfig(source?: LensComboConfigSource | string | null) {
  if (source && typeof source === 'object') {
    const allowed = (source.allowed_lens_combos || []).filter(
      (combo): combo is LensCombo => LENS_COMBO_VALUES.includes(combo as LensCombo),
    )
    if (allowed.length && source.default_lens_combo && allowed.includes(source.default_lens_combo)) {
      return { allowed: [...allowed], default: source.default_lens_combo }
    }
    return compatibilityConfig(source.name)
  }
  return compatibilityConfig(typeof source === 'string' ? source : undefined)
}

export function getAllowedCombos(source?: LensComboConfigSource | string | null): LensCombo[] {
  return resolveConfig(source).allowed
}

export function getDefaultCombo(source?: LensComboConfigSource | string | null): LensCombo {
  return resolveConfig(source).default
}

export function isComboAllowed(source: LensComboConfigSource | string | null | undefined, combo: LensCombo | string | null | undefined): boolean {
  return Boolean(combo && resolveConfig(source).allowed.includes(combo as LensCombo))
}

export function lensComboDisplay(combo?: LensCombo | string | null): string {
  if (!combo) return ''
  return LENS_COMBO_DISPLAY[combo as LensCombo] ?? combo
}
