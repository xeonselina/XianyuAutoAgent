<template>
  <div class="app-container">
    <header v-if="auth.session" class="mobile-tenant-header">
      <strong>{{ auth.session.tenant.name }}</strong>
      <span v-if="tenant.warehouses.length === 1">
        {{ tenant.warehouses[0].name }}
      </span>
      <select
        v-else-if="tenant.warehouses.length > 1"
        :value="tenant.currentWarehouseId"
        aria-label="当前仓库"
        @change="selectWarehouse"
      >
        <option value="all">全部仓库</option>
        <option
          v-for="warehouse in tenant.warehouses"
          :key="warehouse.id"
          :value="warehouse.id"
        >
          {{ warehouse.name }}
        </option>
      </select>
      <span>{{ auth.session.member.role === 'admin' ? 'Admin' : 'Operator' }}</span>
      <button type="button" class="logout-button" @click="logout">退出</button>
    </header>
    <!-- 主内容区 -->
    <main
      class="app-content"
      :class="{ 'app-content--with-tabbar': showTabbar }"
      v-if="auth.session"
      data-testid="app-content"
    >
      <router-view v-slot="{ Component }">
        <keep-alive :include="['GanttView', 'BatchShippingView']">
          <component :is="Component" />
        </keep-alive>
      </router-view>
    </main>

    <!-- 底部标签栏（仅在主视图显示） -->
    <van-tabbar
      v-if="auth.session && showTabbar"
      v-model="activeTab"
      @change="onTabChange"
      safe-area-inset-bottom
    >
      <van-tabbar-item name="gantt" icon="calendar-o">甘特图</van-tabbar-item>
      <van-tabbar-item name="batch-shipping" icon="logistics">批量发货</van-tabbar-item>
      <van-tabbar-item name="relay" icon="exchange">接力</van-tabbar-item>
    </van-tabbar>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useMobileAuthStore } from '@/stores/auth'
import { useMobileTenantStore } from '@/stores/tenant'

const route = useRoute()
const router = useRouter()
const activeTab = ref('gantt')
const auth = useMobileAuthStore()
const tenant = useMobileTenantStore()

const selectWarehouse = (event: Event) => {
  const value = (event.target as HTMLSelectElement).value
  tenant.selectWarehouse(value === 'all' ? 'all' : Number(value))
}

const logout = async () => {
  await auth.logoutToDesktopLogin(`/mobile${route.fullPath}`)
}

const showTabbar = computed(() => {
  return route.name === 'gantt' || route.name === 'batch-shipping' || route.name === 'relay'
})

watch(
  () => route.name,
  name => {
    if (typeof name === 'string' && ['gantt', 'batch-shipping', 'relay'].includes(name)) {
      activeTab.value = name
    }
  },
  { immediate: true }
)

const onTabChange = (name: string) => {
  router.push({ name })
}

watch(
  () => auth.session,
  (session) => {
    if (session) void tenant.initialize().catch(() => undefined)
  },
  { immediate: true },
)
</script>

<style>
html, body, #app {
  height: 100%;
  overflow: hidden;
}

.app-container {
  height: 100%;
  display: flex;
  flex-direction: column;
}

.app-content {
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

.mobile-tenant-header {
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 42px;
  padding: 6px 12px;
  border-bottom: 1px solid #ebedf0;
  background: #fff;
}

.mobile-tenant-header strong { margin-right: auto; }
.mobile-tenant-header select { max-width: 145px; }
.logout-button { border: 0; color: #57606a; background: transparent; }

/* 标签栏是 fixed 定位，需要给页面内容留出等高空间，避免最后一行被遮挡。 */
.app-content--with-tabbar {
  box-sizing: border-box;
  padding-bottom: calc(var(--van-tabbar-height) + env(safe-area-inset-bottom));
}

/* Vant 主题色 */
:root {
  --van-primary-color: #409eff;
  --van-tabbar-height: 50px;
}
</style>
