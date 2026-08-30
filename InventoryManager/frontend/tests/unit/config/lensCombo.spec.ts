import { describe, expect, it } from 'vitest'

import {
  getAllowedCombos,
  getDefaultCombo,
  getProductLines,
  isComboAllowed,
  type LensCombo,
} from '@/config/lensCombo'


describe('lens combo model configuration', () => {
  it('uses the canonical model configuration returned by the API', () => {
    const model = {
      name: 'x200u',
      allowed_lens_combos: ['lens_400mm', 'lens_dual'] as LensCombo[],
      default_lens_combo: 'lens_dual' as const,
    }

    expect(getAllowedCombos(model)).toEqual(['lens_400mm', 'lens_dual'])
    expect(getDefaultCombo(model)).toBe('lens_dual')
    expect(isComboAllowed(model, 'lens_dual')).toBe(true)
    expect(isComboAllowed(model, 'lens_200mm')).toBe(false)
  })

  it('keeps a compatibility fallback for legacy model strings', () => {
    expect(getDefaultCombo('VIVO X300U 16+512')).toBe('lens_400mm')
    expect(getAllowedCombos('unknown')).toEqual(['lens_200mm', 'bare'])
  })

  it('uses the canonical display name on shipping product lines', () => {
    expect(getProductLines('camera-pro', 'bare', '演唱会相机 Pro')[0]).toEqual({
      name: '演唱会相机 Pro',
      qty: 1,
      is_main: true,
    })
  })
})
