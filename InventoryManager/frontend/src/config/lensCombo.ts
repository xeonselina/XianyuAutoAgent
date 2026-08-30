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

export const MODEL_DISPLAY: Record<string, string> = {
  x200u:   'VIVO X200 Ultra 16+512G',
  x300pro: 'VIVO X300 Pro',
  x300u:   'VIVO X300 Ultra',
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

export const LENS_COMBO_DISPLAY: Record<LensCombo, string> = {
  lens_400mm: '400MM 镜头',
  lens_200mm: '200MM 镜头',
  bare:       '裸机',
  lens_dual:  '双镜头',
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

export function modelDisplay(modelName?: string | null, displayName?: string | null): string {
  if (displayName) return displayName
  if (!modelName) return '主机'
  return MODEL_DISPLAY[modelName] ?? modelName
}

export interface ProductLine {
  name: string
  qty: number
  is_main: boolean
}

/**
 * 根据机型 + 镜头组合返回品名清单（与后端 get_product_lines 等价）。
 */
export function getProductLines(modelName?: string | null, lensCombo?: LensCombo | string | null, displayName?: string | null): ProductLine[] {
  const combo = (lensCombo as LensCombo) || getDefaultCombo(modelName)
  const lines: ProductLine[] = [
    { name: modelDisplay(modelName, displayName), qty: 1, is_main: true },
    { name: '90w 充电头+充电线', qty: 1, is_main: false },
  ]

  if (combo === 'lens_400mm') {
    lines.push({ name: '400MM 增距镜+增距镜脚架+手机壳', qty: 1, is_main: false })
  } else if (combo === 'lens_200mm') {
    lines.push({ name: '200MM 镜头+手机壳', qty: 1, is_main: false })
  } else if (combo === 'lens_dual') {
    lines.push({ name: '400MM 增距镜+增距镜脚架+手机壳', qty: 1, is_main: false })
    lines.push({ name: '200MM 镜头', qty: 1, is_main: false })
  }
  // bare: 不追加镜头行

  if (combo !== 'bare') {
    lines.push({ name: '套装便携手提包', qty: 1, is_main: false })
  }
  return lines
}
