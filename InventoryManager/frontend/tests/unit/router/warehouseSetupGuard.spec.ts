import type { RouteLocationNormalized } from 'vue-router'
import { describe, expect, it, vi } from 'vitest'

import { createWarehouseSetupGuard } from '@/router/warehouseSetupGuard'
import type { WarehouseSummary } from '@/api/warehouse'

const route = (name: string, path = `/${name}`): RouteLocationNormalized => (
  { name, path } as RouteLocationNormalized
)

const warehouse = (setupState: WarehouseSummary['setup_state']): WarehouseSummary => ({
  id: 1,
  warehouse_uuid: 'warehouse-1',
  name: '默认仓库',
  status: 'active',
  setup_state: setupState,
  is_default: true,
  contact_name: null,
  contact_phone: '13800138000',
  province: null,
  city: null,
  district: null,
  address_detail: null,
})

describe('warehouse setup route guard', () => {
  it('redirects an authenticated pending tenant away from business routes', async () => {
    const guard = createWarehouseSetupGuard(
      vi.fn().mockResolvedValue(warehouse('pending')),
    )

    await expect(guard(route('gantt'), route('gantt'), () => undefined))
      .resolves.toEqual({ name: 'warehouse-setup' })
  })

  it('allows the pending tenant to remain on the setup route', async () => {
    const guard = createWarehouseSetupGuard(
      vi.fn().mockResolvedValue(warehouse('pending')),
    )

    await expect(guard(route('warehouse-setup'), route('gantt'), () => undefined))
      .resolves.toBe(true)
  })

  it('keeps account security reachable while warehouse setup is pending', async () => {
    const guard = createWarehouseSetupGuard(
      vi.fn().mockResolvedValue(warehouse('pending')),
    )

    await expect(guard(route('account-security'), route('gantt'), () => undefined))
      .resolves.toBe(true)
  })

  it('keeps a ready tenant out of the setup route', async () => {
    const guard = createWarehouseSetupGuard(
      vi.fn().mockResolvedValue(warehouse('ready')),
    )

    await expect(guard(route('warehouse-setup'), route('gantt'), () => undefined))
      .resolves.toEqual({ name: 'gantt' })
  })

  it('does not invent a redirect when authority cannot be established', async () => {
    const guard = createWarehouseSetupGuard(
      vi.fn().mockRejectedValue(new Error('unavailable')),
    )

    await expect(guard(route('gantt'), route('gantt'), () => undefined))
      .resolves.toBe(true)
  })

  it('does not probe tenant setup authority inside the platform namespace', async () => {
    const loadSetup = vi.fn()
    const guard = createWarehouseSetupGuard(loadSetup)

    await expect(
      guard(route('platform-login', '/platform/login'), route('gantt'), () => undefined),
    ).resolves.toBe(true)
    expect(loadSetup).not.toHaveBeenCalled()
  })
})
