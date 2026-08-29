<script setup lang="ts">
import MemberSettings from '@/components/settings/MemberSettings.vue'
import WarehouseSettings from '@/components/settings/WarehouseSettings.vue'
import XianyuShopSettings from '@/components/settings/XianyuShopSettings.vue'
</script>

<template>
  <main class="settings-shell">
    <h1>店铺设置</h1>
    <el-tabs>
      <el-tab-pane label="团队成员"><MemberSettings /></el-tab-pane>
      <el-tab-pane label="仓库与发货"><WarehouseSettings /></el-tab-pane>
      <el-tab-pane label="闲鱼 API">
        <XianyuShopSettings />
      </el-tab-pane>
    </el-tabs>
  </main>
</template>

<style scoped>
.settings-shell { max-width: 1100px; margin: 0 auto; padding: 32px 24px; }
</style>
