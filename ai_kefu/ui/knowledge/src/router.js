import { createRouter, createWebHashHistory } from 'vue-router'
import KnowledgeList from './components/KnowledgeList.vue'
import KnowledgeForm from './components/KnowledgeForm.vue'
import PromptList from './components/PromptList.vue'
import PromptEditor from './components/PromptEditor.vue'
import EvalReplay from './components/EvalReplay.vue'
import IgnorePatternList from './components/IgnorePatternList.vue'
import ConversationHistory from './components/ConversationHistory.vue'
import Settings from './components/Settings.vue'

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
  },
  {
    path: '/ignore-patterns',
    name: 'ignore-patterns',
    component: IgnorePatternList
  },
  {
    path: '/history',
    name: 'history-list',
    component: ConversationHistory
  },
  {
    path: '/history/:chatId',
    name: 'history-detail',
    component: ConversationHistory,
    props: true
  },
  {
    path: '/settings',
    name: 'settings',
    component: Settings
  }
]

const router = createRouter({
  history: createWebHashHistory(),
  routes
})

export default router
