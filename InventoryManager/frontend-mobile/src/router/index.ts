import { createRouter, createWebHistory } from 'vue-router'
import GanttView from '@/views/GanttView.vue'
import BatchShippingView from '@/views/BatchShippingView.vue'
import CreateRentalView from '@/views/CreateRentalView.vue'
import EditRentalView from '@/views/EditRentalView.vue'
import { createWarehouseSetupGuard } from './warehouseSetupGuard'

const router = createRouter({
  history: createWebHistory('/mobile/'),
  routes: [
    {
      path: '/login',
      name: 'tenant-login',
      component: () => import('@/views/TenantLoginView.vue')
    },
    {
      path: '/invite',
      name: 'invitation-acceptance',
      component: () => import('@/views/InvitationAcceptanceView.vue')
    },
    {
      path: '/tenant/status',
      name: 'tenant-status',
      component: () => import('@/views/TenantStatusView.vue')
    },
    {
      path: '/',
      redirect: '/gantt'
    },
    {
      path: '/gantt',
      name: 'gantt',
      component: GanttView
    },
    {
      path: '/batch-shipping',
      name: 'batch-shipping',
      component: BatchShippingView
    },
    {
      path: '/create-rental',
      name: 'create-rental',
      component: CreateRentalView
    },
    {
      path: '/edit-rental/:id',
      name: 'edit-rental',
      component: EditRentalView
    },
    {
      path: '/device-status',
      name: 'device-status',
      component: () => import('@/views/DeviceStatusView.vue')
    },
    {
      path: '/search',
      name: 'search',
      component: () => import('@/views/SearchView.vue')
    },
    {
      path: '/customer-history',
      name: 'customer-history',
      component: () => import('@/views/CustomerHistoryView.vue')
    },
    {
      path: '/relay',
      name: 'relay',
      component: () => import('@/views/RelayManagementView.vue')
    },
    {
      path: '/setup/warehouse',
      name: 'warehouse-setup',
      component: () => import('@/views/WarehouseSetupView.vue')
    },
    {
      path: '/account/security',
      name: 'account-security',
      component: () => import('@/views/AccountSecurityView.vue')
    },
    {
      path: '/members',
      name: 'tenant-members',
      component: () => import('@/views/TenantMembersView.vue')
    },
    {
      path: '/integrations',
      name: 'tenant-integrations',
      component: () => import('@/views/TenantIntegrationsView.vue')
    }
  ],
  scrollBehavior(to, from, savedPosition) {
    if (savedPosition) {
      return savedPosition
    }
    return { top: 0 }
  }
})

router.beforeEach(createWarehouseSetupGuard())

export default router
