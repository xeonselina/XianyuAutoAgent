import { createRouter, createWebHistory } from 'vue-router'
import GanttView from '../views/GanttView.vue'
import RentalContractView from '../views/RentalContractView.vue'
import ShippingOrderView from '../views/ShippingOrderView.vue'
import BatchShippingOrderView from '../views/BatchShippingOrderView.vue'
import BatchShippingView from '../views/BatchShippingView.vue'
import StatisticsView from '../views/StatisticsView.vue'
import SFTrackingView from '../views/SFTrackingView.vue'
import InspectionView from '../views/InspectionView.vue'
import InspectionRecordsView from '../views/InspectionRecordsView.vue'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
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
      path: '/sf-tracking',
      name: 'sf-tracking',
      component: SFTrackingView,
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
    }
  ],
})

export default router
