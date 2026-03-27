import { createRouter, createWebHashHistory } from 'vue-router'
import KnowledgeList from './components/KnowledgeList.vue'
import KnowledgeForm from './components/KnowledgeForm.vue'
import PromptList from './components/PromptList.vue'
import PromptEditor from './components/PromptEditor.vue'
import EvalReplay from './components/EvalReplay.vue'

const routes = [
  {
    path: '/',
    name: 'knowledge-list',
    component: KnowledgeList
  },
  {
    path: '/new',
    name: 'knowledge-new',
    component: KnowledgeForm
  },
  {
    path: '/edit/:id',
    name: 'knowledge-edit',
    component: KnowledgeForm,
    props: true
  },
  {
    path: '/prompts',
    name: 'prompt-list',
    component: PromptList
  },
  {
    path: '/prompts/new',
    name: 'prompt-new',
    component: PromptEditor
  },
  {
    path: '/prompts/edit/:id',
    name: 'prompt-edit',
    component: PromptEditor,
    props: true
  },
  {
    path: '/eval',
    name: 'eval-list',
    component: EvalReplay
  },
  {
    path: '/eval/:runId',
    name: 'eval-detail',
    component: EvalReplay,
    props: true
  }
]

const router = createRouter({
  history: createWebHashHistory(),
  routes
})

export default router
