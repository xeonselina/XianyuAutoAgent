<template>
  <div id="app">
    <router-view v-slot="{ Component }">
      <keep-alive>
        <component :is="Component" />
      </keep-alive>
    </router-view>
    
    <!-- 底部导航栏 -->
    <van-tabbar v-model="active" route fixed>
      <van-tabbar-item to="/gantt" icon="calendar-o">
        档期
      </van-tabbar-item>
      <van-tabbar-item to="/booking" icon="add-o">
        预约
      </van-tabbar-item>
    </van-tabbar>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'

const active = ref(0)
</script>

<style>
body {
  margin: 0;
  padding: 0;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
}

#app {
  min-height: 100vh;
  background: #f7f8fa;
}
</style>
