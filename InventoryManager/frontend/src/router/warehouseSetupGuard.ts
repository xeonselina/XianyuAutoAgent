import type {
  NavigationGuard,
  RouteLocationNormalized,
  RouteLocationRaw,
} from 'vue-router'

import {
  getDefaultWarehouseSetup,
  type WarehouseSummary,
} from '@/api/warehouse'

type SetupLoader = () => Promise<WarehouseSummary>

const SETUP_ROUTE_NAME = 'warehouse-setup'
const PENDING_ALLOWED_ROUTE_NAMES = new Set([
  SETUP_ROUTE_NAME,
  'account-security',
  'tenant-login',
  'tenant-status',
  'invitation-acceptance',
  'tenant-members',
])

/**
 * Route-level setup gate for the desktop shell.
 *
 * Authentication and tenant authority stay on the server.  A failed probe is
 * deliberately not interpreted by the client; the requested page will surface
 * the authoritative 401/403/503 response.  Only a successful, authenticated
 * `pending` result may redirect a user to the setup route.
 */
export function createWarehouseSetupGuard(
  loadSetup: SetupLoader = getDefaultWarehouseSetup,
): NavigationGuard {
  return async (to: RouteLocationNormalized): Promise<true | RouteLocationRaw> => {
    const targetPath = String(to.path || '')
    if (to.name === 'invitation-acceptance') return true
    if (targetPath === '/platform' || targetPath.startsWith('/platform/')) {
      return true
    }
    try {
      const warehouse = await loadSetup()
      if (
        warehouse.setup_state === 'pending'
        && !PENDING_ALLOWED_ROUTE_NAMES.has(String(to.name || ''))
      ) {
        return { name: SETUP_ROUTE_NAME }
      }
      if (warehouse.setup_state === 'ready' && to.name === SETUP_ROUTE_NAME) {
        return { name: 'gantt' }
      }
    } catch {
      // Never guess whether an unavailable response means unauthenticated,
      // forbidden, or temporarily unconfigured.  The destination API remains
      // the source of truth for those states.
    }
    return true
  }
}
