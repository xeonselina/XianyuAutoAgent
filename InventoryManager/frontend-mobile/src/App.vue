<template>
  <div class="app-container">
    <!-- 主内容区 -->
    <main
      class="app-content"
      :class="{ 'app-content--with-tabbar': showTabbar }"
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
      v-if="showTabbar"
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

const route = useRoute()
const router = useRouter()
const activeTab = ref('gantt')

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
