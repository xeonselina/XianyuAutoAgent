import {
  createRouter,
  createWebHistory,
  type Router,
} from 'vue-router'

import { useAuthStore } from '@/stores/auth'
import GanttView from '@/views/GanttView.vue'
import RentalContractView from '@/views/RentalContractView.vue'
import ShippingOrderView from '@/views/ShippingOrderView.vue'
import BatchShippingOrderView from '@/views/BatchShippingOrderView.vue'
import BatchShippingView from '@/views/BatchShippingView.vue'
import StatisticsView from '@/views/StatisticsView.vue'
import RentalStatsView from '@/views/RentalStatsView.vue'
import SFTrackingView from '@/views/SFTrackingView.vue'
import InspectionView from '@/views/InspectionView.vue'
import InspectionRecordsView from '@/views/InspectionRecordsView.vue'


declare module 'vue-router' {
  interface RouteMeta {
    public?: boolean
    platform?: boolean
    requiresTenant?: boolean
  }
}

type AuthGuardStore = Pick<
  ReturnType<typeof useAuthStore>,
  | 'accessStatus'
  | 'authenticated'
  | 'bootstrap'
  | 'bootstrapPlatform'
  | 'member'
  | 'platformAuthenticated'
>

export const installAuthGuards = (
  router: Router,
  getAuth: () => AuthGuardStore = useAuthStore,
) => {
  router.beforeEach(async (to) => {
    if (to.meta.public) return true

    const auth = getAuth()
    if (to.meta.platform) {
      await auth.bootstrapPlatform()
      if (!auth.platformAuthenticated) {
        return {
          name: 'platform-login',
          query: { next: to.fullPath },
        }
      }
      return true
    }

    if (!to.meta.requiresTenant) return true
    await auth.bootstrap()
    if (!auth.authenticated) {
      return { name: 'login', query: { next: to.fullPath } }
    }

    const isRestrictedPage = to.name === 'access-restricted'
    if (to.path === '/settings' && auth.member?.role !== 'admin') {
      return isRestrictedPage
        ? true
        : { name: 'access-restricted', query: { reason: 'forbidden' } }
    }
    if (auth.accessStatus !== 'active') {
      return isRestrictedPage
        ? true
        : {
            name: 'access-restricted',
            query: { reason: auth.accessStatus || 'restricted' },
          }
    }
    if (isRestrictedPage && to.query.reason !== 'forbidden') {
      return { name: 'gantt' }
    }
    return true
  })
}

const requiresTenant = { requiresTenant: true }

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/login',
      name: 'login',
      component: () => import('@/views/LoginView.vue'),
      meta: { public: true },
    },
    {
      path: '/access-restricted',
      name: 'access-restricted',
      component: () => import('@/views/AccessRestrictedView.vue'),
      meta: requiresTenant,
    },
    {
      path: '/settings',
      name: 'settings',
      component: () => import('@/views/SettingsView.vue'),
      meta: requiresTenant,
    },
    {
      path: '/platform/login',
      name: 'platform-login',
      component: () => import('@/views/PlatformLoginView.vue'),
      meta: { public: true, platform: true },
    },
    {
      path: '/platform/tenants',
      name: 'platform-tenants',
      component: () => import('@/views/PlatformTenantsView.vue'),
      meta: { platform: true },
    },
    { path: '/', name: 'gantt', component: GanttView, meta: requiresTenant },
    { path: '/gantt', redirect: '/' },
    {
      path: '/contract/:id',
      name: 'rental-contract',
      component: RentalContractView,
      meta: requiresTenant,
    },
    {
      path: '/shipping/:id',
      name: 'shipping-order',
      component: ShippingOrderView,
      meta: requiresTenant,
    },
    {
      path: '/batch-shipping-order',
      name: 'batch-shipping-order',
      component: BatchShippingOrderView,
      meta: requiresTenant,
    },
    {
      path: '/batch-shipping',
      name: 'batch-shipping',
      component: BatchShippingView,
      meta: requiresTenant,
    },
    {
      path: '/statistics',
      name: 'statistics',
      component: StatisticsView,
      meta: requiresTenant,
    },
    {
      path: '/rental-stats',
      name: 'rental-stats',
      component: RentalStatsView,
      meta: requiresTenant,
    },
    {
      path: '/sf-tracking',
      name: 'sf-tracking',
      component: SFTrackingView,
      meta: requiresTenant,
    },
    {
      path: '/relay-management',
      name: 'relay-management',
      component: () => import('@/views/RelayManagementView.vue'),
      meta: requiresTenant,
    },
    {
      path: '/inspection',
      name: 'inspection',
      component: InspectionView,
      meta: requiresTenant,
    },
    {
      path: '/inspection-records',
      name: 'inspection-records',
      component: InspectionRecordsView,
      meta: requiresTenant,
    },
  ],
})

installAuthGuards(router)

export default router
