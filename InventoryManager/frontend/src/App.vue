<script setup lang="ts">
import { computed } from 'vue'
import { RouterView, useRoute } from 'vue-router'

import { useAuthStore } from '@/stores/auth'
import AppHeader from '@/components/AppHeader.vue'


const auth = useAuthStore()
const route = useRoute()
const showTenantHeader = computed(
  () => Boolean(route.meta.requiresTenant && auth.authenticated),
)
</script>

<template>
  <div id="app">
    <AppHeader v-if="showTenantHeader" />
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

.logistics-warning-confirm {
  --el-button-bg-color: var(--el-color-warning);
  --el-button-border-color: var(--el-color-warning);
  --el-button-hover-bg-color: var(--el-color-warning-light-3);
  --el-button-hover-border-color: var(--el-color-warning-light-3);
  --el-button-active-bg-color: var(--el-color-warning-dark-2);
  --el-button-active-border-color: var(--el-color-warning-dark-2);
}
</style>
