import { createRouter, createWebHistory } from 'vue-router'
import GanttView from '@/views/GanttView.vue'
import BatchShippingView from '@/views/BatchShippingView.vue'
import CreateRentalView from '@/views/CreateRentalView.vue'
import EditRentalView from '@/views/EditRentalView.vue'

const router = createRouter({
  history: createWebHistory('/mobile/'),
  routes: [
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
    }
  ],
  scrollBehavior(to, from, savedPosition) {
    if (savedPosition) {
      return savedPosition
    }
    return { top: 0 }
  }
})

export default router
