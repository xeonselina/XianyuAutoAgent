<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { RouterLink, useRoute } from 'vue-router'

import { useAuthStore } from '@/stores/auth'
import { useTenantStore } from '@/stores/tenant'


const auth = useAuthStore()
const tenant = useTenantStore()
const route = useRoute()
const accountMenu = ref<HTMLDetailsElement>()

const primaryNavigation = [
  { key: 'schedule', label: '档期管理', to: '/' },
  { key: 'devices', label: '设备管理', to: '/devices' },
  { key: 'statistics', label: '统计', to: '/rental-stats' },
  { key: 'operations', label: '收货发货', to: '/operations' },
] as const

const activeSection = computed(() => {
  const path = route.path
  if (path === '/devices' || path.startsWith('/devices/')) return 'devices'
  if (path === '/rental-stats' || path === '/statistics') return 'statistics'
  if (
    path === '/operations'
    || path.startsWith('/batch-shipping')
    || path.startsWith('/shipping/')
    || path.startsWith('/inspection')
    || path === '/relay-management'
    || path === '/sf-tracking'
  ) return 'operations'
  return 'schedule'
})

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
      <span class="brand-eyebrow">店铺</span>
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

    <nav class="primary-navigation" aria-label="业务导航">
      <RouterLink
        v-for="item in primaryNavigation"
        :key="item.key"
        :to="item.to"
        class="primary-navigation__item"
        :class="{ 'is-active': activeSection === item.key }"
        :data-testid="`primary-nav-${item.key}`"
      >
        {{ item.label }}
      </RouterLink>
    </nav>

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
  gap: 14px;
  min-height: 42px;
  padding: 3px 14px;
  color: #344054;
  background: rgb(255 255 255 / 94%);
  border-bottom: 1px solid #e4e7ec;
  backdrop-filter: blur(8px);
}

.brand-block { display: flex; align-items: center; min-width: 142px; max-width: 210px; gap: 6px; color: inherit; text-decoration: none; }
.brand-block strong { overflow: hidden; color: #101828; font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }
.brand-eyebrow, .context-label { flex: none; color: #98a2b3; font-size: 11px; letter-spacing: .02em; }
.warehouse-context { display: flex; align-items: center; min-width: 132px; gap: 6px; }
.warehouse-selector { width: 118px; }
.warehouse-name, .warehouse-empty { overflow: hidden; color: #344054; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.warehouse-empty { color: #98a2b3; }
.primary-navigation { display: flex; align-self: stretch; justify-content: center; flex: 1; min-width: 0; gap: 2px; }
.primary-navigation__item { position: relative; display: flex; align-items: center; padding: 0 13px; border-radius: 6px; color: #475467; font-size: 13px; font-weight: 600; text-decoration: none; white-space: nowrap; }
.primary-navigation__item:hover { color: #175cd3; background: #f2f4f7; }
.primary-navigation__item.is-active { color: #175cd3; background: #eff4ff; }
.primary-navigation__item.is-active::after { position: absolute; right: 12px; bottom: -3px; left: 12px; height: 2px; border-radius: 2px 2px 0 0; background: #2e90fa; content: ''; }
.account-menu { position: relative; }
.account-menu summary { display: flex; align-items: center; min-width: 142px; gap: 7px; padding: 3px 6px; border-radius: 7px; cursor: pointer; list-style: none; }
.account-menu summary::-webkit-details-marker { display: none; }
.account-menu summary:hover, .account-menu[open] summary { background: #f2f4f7; }
.avatar { display: grid; width: 26px; height: 26px; place-items: center; border-radius: 50%; color: #175cd3; background: #eaf2ff; font-size: 11px; font-weight: 700; }
.account-summary { display: flex; flex: 1; }
.account-summary strong { color: #101828; font-size: 12px; font-weight: 600; white-space: nowrap; }
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
@media (max-width: 1080px) {
  .tenant-header { gap: 8px; padding-inline: 10px; }
  .brand-eyebrow, .context-label { display: none; }
  .brand-block { min-width: 0; }
  .warehouse-context { min-width: 104px; }
  .warehouse-selector { width: 104px; }
  .primary-navigation__item { padding-inline: 9px; }
  .account-menu summary { min-width: auto; }
}
@media (max-width: 760px) {
  .tenant-header { overflow-x: auto; }
  .brand-block { display: none; }
  .primary-navigation { flex: none; order: 2; }
  .primary-navigation__item { padding-inline: 8px; font-size: 12px; }
  .account-menu { order: 3; }
  .account-summary { display: none; }
  .account-menu summary { min-width: auto; }
}
</style>
