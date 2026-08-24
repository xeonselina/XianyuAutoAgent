<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink, RouterView, useRoute, useRouter } from 'vue-router'

import { useAuthStore } from '@/stores/auth'


const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const showTenantHeader = computed(
  () => Boolean(route.meta.requiresTenant && auth.authenticated),
)
const logout = async () => {
  await auth.logout()
  await router.replace('/login')
}
</script>

<template>
  <div id="app">
    <header v-if="showTenantHeader" class="tenant-header">
      <strong>{{ auth.tenant?.name }}</strong>
      <span>{{ auth.member?.role === 'admin' ? 'Admin' : 'Operator' }}</span>
      <RouterLink
        v-if="auth.member?.role === 'admin'"
        data-testid="settings-link"
        to="/settings"
      >
        设置
      </RouterLink>
      <button type="button" @click="logout">退出登录</button>
    </header>
    <RouterView />
  </div>
</template>

<style>
#app {
  margin: 0;
  padding: 0;
  min-height: 100vh;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
}

* {
  box-sizing: border-box;
}

body {
  margin: 0;
  padding: 0;
}

.tenant-header {
  position: sticky;
  z-index: 30;
  top: 0;
  display: flex;
  align-items: center;
  gap: 14px;
  min-height: 48px;
  padding: 8px 18px;
  color: #344054;
  background: rgb(255 255 255 / 94%);
  border-bottom: 1px solid #e4e7ec;
  backdrop-filter: blur(8px);
}

.tenant-header strong { margin-right: auto; color: #101828; }
.tenant-header a { color: #175cd3; }
.tenant-header button { border: 0; color: #475467; background: transparent; cursor: pointer; }

.logistics-warning-confirm {
  --el-button-bg-color: var(--el-color-warning);
  --el-button-border-color: var(--el-color-warning);
  --el-button-hover-bg-color: var(--el-color-warning-light-3);
  --el-button-hover-border-color: var(--el-color-warning-light-3);
  --el-button-active-bg-color: var(--el-color-warning-dark-2);
  --el-button-active-border-color: var(--el-color-warning-dark-2);
}
</style>
