<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'

import { useAuthStore } from '@/stores/auth'
import { useTenantStore } from '@/stores/tenant'


const auth = useAuthStore()
const tenant = useTenantStore()
const accountMenu = ref<HTMLDetailsElement>()

const roleLabel = computed(() => (
  auth.member?.role === 'admin' ? '店铺管理员' : '店铺成员'
))
const displayPhone = computed(() => {
  const phone = auth.member?.phone || ''
  const local = phone.startsWith('+86') ? phone.slice(3) : phone
  if (local.length !== 11) return local || '当前用户'
  return `${local.slice(0, 3)} ${local.slice(3, 7)} ${local.slice(7)}`
})
const avatarLabel = computed(() => (
  auth.member?.role === 'admin' ? '管' : '员'
))

const closeAccountMenu = () => {
  if (accountMenu.value) accountMenu.value.open = false
}

const closeAccountMenuFromOutside = (event: PointerEvent) => {
  if (!accountMenu.value?.contains(event.target as Node)) closeAccountMenu()
}

const logout = async () => {
  closeAccountMenu()
  await auth.logoutTo('/login')
}

onMounted(() => {
  document.addEventListener('pointerdown', closeAccountMenuFromOutside)
  void tenant.initialize().catch(() => undefined)
})
onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', closeAccountMenuFromOutside)
})
</script>

<template>
  <header class="tenant-header">
    <RouterLink to="/" class="brand-block">
      <span class="brand-eyebrow">店铺工作台</span>
      <strong>{{ auth.tenant?.name }}</strong>
    </RouterLink>

    <div class="warehouse-context">
      <span class="context-label">当前仓库</span>
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
      <span v-else class="warehouse-empty">尚未配置</span>
    </div>

    <details
      ref="accountMenu"
      class="account-menu"
      data-testid="user-menu"
      @keydown.esc="closeAccountMenu"
    >
      <summary>
        <span class="avatar" aria-hidden="true">{{ avatarLabel }}</span>
        <span class="account-summary">
          <strong>{{ displayPhone }}</strong>
          <small>{{ roleLabel }}</small>
        </span>
        <span class="chevron" aria-hidden="true">⌄</span>
      </summary>
      <nav class="account-popover" aria-label="账号菜单">
        <div class="account-identity">
          <strong>{{ displayPhone }}</strong>
          <span>{{ roleLabel }}</span>
        </div>
        <RouterLink
          v-if="auth.member?.role === 'admin'"
          data-testid="settings-link"
          class="menu-item"
          to="/settings"
          @click="closeAccountMenu"
        >
          <span>店铺设置</span>
          <small>团队成员、仓库与闲鱼 API</small>
        </RouterLink>
        <RouterLink
          v-if="auth.authMethod === 'password'"
          data-testid="change-password-link"
          class="menu-item"
          to="/change-password"
          @click="closeAccountMenu"
        >
          <span>账号安全</span>
          <small>修改当前登录密码</small>
        </RouterLink>
        <div class="menu-divider" />
        <button type="button" class="menu-item logout-item" @click="logout">
          退出登录
        </button>
      </nav>
    </details>
  </header>
</template>

<style scoped>
.tenant-header {
  position: sticky;
  z-index: 30;
  top: 0;
  display: flex;
  align-items: center;
  gap: 24px;
  min-height: 58px;
  padding: 8px 20px;
  color: #344054;
  background: rgb(255 255 255 / 94%);
  border-bottom: 1px solid #e4e7ec;
  backdrop-filter: blur(8px);
}

.brand-block { display: grid; flex: 1; min-width: 150px; color: inherit; text-decoration: none; }
.brand-block strong { overflow: hidden; color: #101828; font-size: 16px; text-overflow: ellipsis; white-space: nowrap; }
.brand-eyebrow, .context-label { color: #98a2b3; font-size: 11px; letter-spacing: .04em; }
.warehouse-context { display: grid; min-width: 150px; gap: 2px; }
.warehouse-selector { width: 150px; }
.warehouse-name, .warehouse-empty { color: #344054; font-size: 14px; }
.warehouse-empty { color: #98a2b3; }
.account-menu { position: relative; }
.account-menu summary { display: flex; align-items: center; min-width: 184px; gap: 10px; padding: 5px 8px; border-radius: 10px; cursor: pointer; list-style: none; }
.account-menu summary::-webkit-details-marker { display: none; }
.account-menu summary:hover, .account-menu[open] summary { background: #f2f4f7; }
.avatar { display: grid; width: 34px; height: 34px; place-items: center; border-radius: 50%; color: #175cd3; background: #eaf2ff; font-size: 13px; font-weight: 700; }
.account-summary { display: grid; flex: 1; }
.account-summary strong { color: #101828; font-size: 13px; font-weight: 600; }
.account-summary small { color: #667085; font-size: 11px; }
.chevron { color: #98a2b3; }
.account-popover { position: absolute; top: calc(100% + 8px); right: 0; display: grid; width: 260px; padding: 8px; border: 1px solid #e4e7ec; border-radius: 12px; background: white; box-shadow: 0 12px 32px rgb(16 24 40 / 16%); }
.account-identity { display: grid; gap: 3px; padding: 10px 12px 12px; }
.account-identity strong { color: #101828; font-size: 14px; }
.account-identity span { color: #667085; font-size: 12px; }
.menu-item { display: grid; gap: 2px; padding: 10px 12px; border: 0; border-radius: 8px; color: #344054; background: transparent; text-align: left; text-decoration: none; cursor: pointer; }
.menu-item:hover { background: #f2f4f7; }
.menu-item span { font-size: 14px; font-weight: 600; }
.menu-item small { color: #667085; font-size: 11px; }
.menu-divider { height: 1px; margin: 6px 4px; background: #eaecf0; }
.logout-item { color: #b42318; font: inherit; }
@media (max-width: 720px) {
  .tenant-header { gap: 12px; padding-inline: 12px; }
  .brand-eyebrow, .context-label, .account-summary { display: none; }
  .brand-block { min-width: 0; }
  .warehouse-context { min-width: 120px; }
  .warehouse-selector { width: 120px; }
  .account-menu summary { min-width: auto; }
}
</style>
