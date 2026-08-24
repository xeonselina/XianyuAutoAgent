import { createRouter, createWebHistory } from 'vue-router'
import GanttView from '../views/GanttView.vue'
import RentalContractView from '../views/RentalContractView.vue'
import ShippingOrderView from '../views/ShippingOrderView.vue'
import BatchShippingOrderView from '../views/BatchShippingOrderView.vue'
import BatchShippingView from '../views/BatchShippingView.vue'
import StatisticsView from '../views/StatisticsView.vue'
import RentalStatsView from '../views/RentalStatsView.vue'
import SFTrackingView from '../views/SFTrackingView.vue'
import InspectionView from '../views/InspectionView.vue'
import InspectionRecordsView from '../views/InspectionRecordsView.vue'
import { createWarehouseSetupGuard } from './warehouseSetupGuard'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/login',
      name: 'tenant-login',
      component: () => import('../views/TenantLoginView.vue'),
    },
    {
      path: '/invite',
      name: 'invitation-acceptance',
      component: () => import('../views/InvitationAcceptanceView.vue'),
    },
    {
      path: '/platform',
      redirect: { name: 'platform-login' },
    },
    {
      path: '/platform/login',
      name: 'platform-login',
      component: () => import('../views/PlatformLoginView.vue'),
    },
    {
      path: '/platform/setup',
      name: 'platform-setup',
      component: () => import('../views/PlatformSetupView.vue'),
    },
    {
      path: '/platform/security',
      name: 'platform-security',
      component: () => import('../views/PlatformAccountSecurityView.vue'),
    },
    {
      path: '/platform/tenants',
      name: 'platform-tenants',
      component: () => import('../views/PlatformTenantsView.vue'),
    },
    {
      path: '/platform/redemption-codes',
      name: 'platform-redemption-codes',
      component: () => import('../views/PlatformRedemptionCodesView.vue'),
    },
    {
      path: '/platform/tenants/:tenantId/subscription-adjustment',
      name: 'platform-subscription-adjustment',
      component: () => import('../views/PlatformSubscriptionAdjustmentView.vue'),
    },
    {
      path: '/tenant/status',
      name: 'tenant-status',
      component: () => import('../views/TenantStatusView.vue'),
    },
    {
      path: '/',
      name: 'gantt',
      component: GanttView,
    },
    {
      path: '/gantt',
      redirect: '/'
    },
    {
      path: '/contract/:id',
      name: 'rental-contract',
      component: RentalContractView,
    },
    {
      path: '/shipping/:id',
      name: 'shipping-order',
      component: ShippingOrderView,
    },
    {
      path: '/batch-shipping-order',
      name: 'batch-shipping-order',
      component: BatchShippingOrderView,
    },
    {
      path: '/batch-shipping',
      name: 'batch-shipping',
      component: BatchShippingView,
    },
    {
      path: '/statistics',
      name: 'statistics',
      component: StatisticsView,
    },
    {
      path: '/rental-stats',
      name: 'rental-stats',
      component: RentalStatsView,
    },
    {
      path: '/sf-tracking',
      name: 'sf-tracking',
      component: SFTrackingView,
    },
    {
      path: '/relay-management',
      name: 'relay-management',
      component: () => import('../views/RelayManagementView.vue'),
    },
    {
      path: '/inspection',
      name: 'inspection',
      component: InspectionView,
    },
    {
      path: '/inspection-records',
      name: 'inspection-records',
      component: InspectionRecordsView,
    },
    {
      path: '/warehouses',
      name: 'warehouse-management',
      component: () => import('../views/WarehouseManagementView.vue'),
    },
    {
      path: '/setup/warehouse',
      name: 'warehouse-setup',
      component: () => import('../views/WarehouseSetupView.vue'),
    },
    {
      path: '/account/security',
      name: 'account-security',
      component: () => import('../views/AccountSecurityView.vue'),
    },
    {
      path: '/members',
      name: 'tenant-members',
      component: () => import('../views/TenantMembersView.vue'),
    },
    {
      path: '/integrations',
      name: 'tenant-integrations',
      component: () => import('../views/TenantIntegrationsView.vue'),
    }
  ],
})

router.beforeEach(createWarehouseSetupGuard())

export default router
