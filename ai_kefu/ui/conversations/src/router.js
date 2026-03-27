import { createRouter, createWebHashHistory } from 'vue-router'
import ConversationList from './components/ConversationList.vue'
import ConversationDetail from './components/ConversationDetail.vue'
import MessageSearch from './components/MessageSearch.vue'

const routes = [
  { path: '/', component: ConversationList },
  { path: '/chat/:chatId', component: ConversationDetail, props: true },
  { path: '/search', component: MessageSearch }
]

const router = createRouter({
  history: createWebHashHistory(),
  routes
})

export default router
