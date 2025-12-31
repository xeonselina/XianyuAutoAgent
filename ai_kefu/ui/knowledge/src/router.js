import { createRouter, createWebHashHistory } from 'vue-router'
import KnowledgeList from './components/KnowledgeList.vue'
import KnowledgeForm from './components/KnowledgeForm.vue'

const routes = [
  {
    path: '/',
    name: 'list',
    component: KnowledgeList
  },
  {
    path: '/new',
    name: 'new',
    component: KnowledgeForm
  },
  {
    path: '/edit/:id',
    name: 'edit',
    component: KnowledgeForm,
    props: true
  }
]

const router = createRouter({
  history: createWebHashHistory(),
  routes
})

export default router
