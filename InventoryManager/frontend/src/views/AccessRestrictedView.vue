<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { useAuthStore } from '@/stores/auth'


const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const reason = computed(() => route.query.reason || auth.accessStatus)
const title = computed(() => {
  if (reason.value === 'expired') return '租户已到期'
  if (reason.value === 'suspended') return '租户已暂停'
  if (reason.value === 'forbidden') return '没有管理权限'
  return '暂时无法访问'
})
const detail = computed(() => reason.value === 'forbidden'
  ? '当前账号为 Operator，只有 Admin 可以进入设置。'
  : '业务数据仍会保留，请联系平台管理员处理租户状态或到期时间。')
const logout = async () => {
  await auth.logout()
  await router.replace('/login')
}
</script>

<template>
  <main class="restricted-page">
    <section>
      <p>{{ auth.tenant?.name }}</p>
      <h1>{{ title }}</h1>
      <p>{{ detail }}</p>
      <button type="button" @click="logout">退出登录</button>
    </section>
  </main>
</template>

<style scoped>
.restricted-page { min-height: 100vh; display: grid; place-items: center; padding: 24px; background: #fff7ed; }
section { max-width: 560px; padding: 36px; border: 1px solid #fed7aa; border-radius: 14px; background: white; }
h1 { color: #9a3412; }
button { padding: 9px 15px; border: 0; border-radius: 8px; color: white; background: #9a3412; cursor: pointer; }
</style>
