<template>
  <div class="app-container">
    <!-- 主内容区 -->
    <router-view v-slot="{ Component }">
      <keep-alive :include="['GanttView', 'BatchShippingView']">
        <component :is="Component" />
      </keep-alive>
    </router-view>

    <!-- 底部标签栏（仅在主视图显示） -->
    <van-tabbar
      v-if="showTabbar"
      v-model="activeTab"
      @change="onTabChange"
      safe-area-inset-bottom
    >
      <van-tabbar-item name="gantt" icon="calendar-o">甘特图</van-tabbar-item>
      <van-tabbar-item name="batch-shipping" icon="logistics">批量发货</van-tabbar-item>
    </van-tabbar>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'

const route = useRoute()
const router = useRouter()
const activeTab = ref('gantt')

const showTabbar = computed(() => {
  return route.name === 'gantt' || route.name === 'batch-shipping'
})

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

.app-container > .router-view-container {
  flex: 1;
  overflow: hidden;
}

/* Vant 主题色 */
:root {
  --van-primary-color: #409eff;
  --van-tabbar-height: 50px;
}
</style>
