/**
 * Vue Router 配置
 * 定义移动端路由结构
 */

import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      redirect: '/gantt'
    },
    {
      path: '/gantt',
      name: 'gantt',
      component: () => import('@/views/GanttView.vue'),
      meta: { title: '设备档期' }
    },
    {
      path: '/booking',
      name: 'booking',
      component: () => import('@/views/BookingView.vue'),
      meta: { title: '预约档期' }
    }
  ]
})

// 设置页面标题
router.beforeEach((to, from, next) => {
  document.title = (to.meta.title as string) || '库存管理'
  next()
})

export default router
