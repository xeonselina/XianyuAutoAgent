<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { RouterLink, useRouter } from 'vue-router'

import { useAuthStore } from '@/stores/auth'
import { useTenantStore } from '@/stores/tenant'


const auth = useAuthStore()
const tenant = useTenantStore()
const router = useRouter()

const roleLabel = computed(() => (
  auth.member?.role === 'admin' ? 'Admin' : 'Operator'
))

const logout = async () => {
  await auth.logout()
  tenant.reset()
  await router.replace('/login')
}

onMounted(() => {
  void tenant.loadWarehouses().catch(() => undefined)
})
</script>

<template>
  <header class="tenant-header">
    <strong>{{ auth.tenant?.name }}</strong>

    <span v-if="tenant.warehouses.length === 1" class="warehouse-name">
      {{ tenant.warehouses[0].name }}
    </span>
    <el-select
      v-else-if="tenant.warehouses.length > 1"
      :model-value="tenant.currentWarehouseId"
      data-testid="warehouse-selector"
      class="warehouse-selector"
      size="small"
      @update:model-value="tenant.selectWarehouse"
    >
      <el-option label="全部仓库" value="all" />
      <el-option
        v-for="warehouse in tenant.warehouses"
        :key="warehouse.id"
        :label="warehouse.name"
        :value="warehouse.id"
      />
    </el-select>

    <span>{{ roleLabel }}</span>
    <RouterLink
      v-if="auth.member?.role === 'admin'"
      data-testid="settings-link"
      to="/settings"
    >
      设置
    </RouterLink>
    <button type="button" @click="logout">退出登录</button>
  </header>
</template>

<style scoped>
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

strong { margin-right: auto; color: #101828; }
a { color: #175cd3; }
button { border: 0; color: #475467; background: transparent; cursor: pointer; }
.warehouse-selector { width: 150px; }
.warehouse-name { color: #475467; }
</style>
