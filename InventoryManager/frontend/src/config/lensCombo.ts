/**
 * 镜头组合配置 - 与后端 app/services/printing/rental_product_lines.py 保持一致
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

export const MODEL_DISPLAY: Record<string, string> = {
  x200u:   'VIVO X200 Ultra 16+512G',
  x300pro: 'VIVO X300 Pro',
  x300u:   'VIVO X300 Ultra',
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

export function modelDisplay(modelName?: string | null): string {
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
export function getProductLines(modelName?: string | null, lensCombo?: LensCombo | string | null): ProductLine[] {
  const combo = (lensCombo as LensCombo) || getDefaultCombo(modelName)
  const lines: ProductLine[] = [
    { name: modelDisplay(modelName), qty: 1, is_main: true },
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
