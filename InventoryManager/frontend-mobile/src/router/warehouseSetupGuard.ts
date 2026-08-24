import type {
  NavigationGuard,
  RouteLocationNormalized,
  RouteLocationRaw,
} from 'vue-router'

import {
  getDefaultWarehouseSetup,
  type DefaultWarehouseSetup,
} from '@/api/warehouseSetup'

type SetupLoader = () => Promise<DefaultWarehouseSetup>
const PENDING_ALLOWED_ROUTE_NAMES = new Set([
  'warehouse-setup',
  'account-security',
  'tenant-login',
  'tenant-status',
  'invitation-acceptance',
  'tenant-members',
])

export function createWarehouseSetupGuard(
  loadSetup: SetupLoader = getDefaultWarehouseSetup,
): NavigationGuard {
  return async (to: RouteLocationNormalized): Promise<true | RouteLocationRaw> => {
    if (to.name === 'invitation-acceptance') return true
    try {
      const warehouse = await loadSetup()
      if (
        warehouse.setup_state === 'pending'
        && !PENDING_ALLOWED_ROUTE_NAMES.has(String(to.name || ''))
      ) {
        return { name: 'warehouse-setup' }
      }
      if (warehouse.setup_state === 'ready' && to.name === 'warehouse-setup') {
        return { name: 'gantt' }
      }
    } catch {
      // The destination API, not the client, decides whether this was an
      // authentication, authorization, or availability failure.
    }
    return true
  }
}
