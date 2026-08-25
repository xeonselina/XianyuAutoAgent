<template>
  <div class="device-status-view">
    <van-nav-bar
      title="设备状态管理"
      left-arrow
      @click-left="$router.back()"
      :border="false"
    />

    <!-- 生命周期状态过滤 -->
    <van-tabs v-model:active="activeTab" sticky>
      <van-tab title="全部" name="all" />
      <van-tab title="使用中" name="active" />
      <van-tab title="已售出" name="sold" />
      <van-tab title="已停用" name="decommissioned" />
      <van-tab title="已损坏" name="damaged" />
      <van-tab title="已退役" name="retired" />
    </van-tabs>

    <div class="device-list" v-if="!ganttStore.loading">
      <van-empty v-if="!filteredDevices.length" description="暂无设备" />
      <template v-else>
        <div
          v-for="device in filteredDevices"
          :key="device.id"
          class="device-card"
        >
          <div class="device-main">
            <div class="device-info">
              <div class="device-name">{{ device.name }}</div>
              <div class="device-sn">{{ device.serial_number }}</div>
              <div class="device-model">{{ device.model }}</div>
            </div>
            <div class="device-badges">
              <van-tag
                :type="lifecycleBadgeType(device.lifecycle_status)"
                class="lifecycle-badge"
                :class="{ 'is-read-only': !canWrite }"
                @click="openLifecyclePicker(device)"
              >
                {{ LIFECYCLE_LABELS[device.lifecycle_status] || device.lifecycle_status }}
              </van-tag>
            </div>
          </div>
        </div>
      </template>
    </div>

    <div class="loading-center" v-else>
      <van-loading color="#409eff" />
    </div>

    <!-- 生命周期 选择 -->
    <van-action-sheet
      v-model:show="showLifecycleSheet"
      title="修改生命周期状态"
      :actions="lifecycleActions"
      cancel-text="取消"
      @select="onLifecycleSelect"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { showToast } from 'vant'
import { useGanttStore } from '@/stores/gantt'
import type { Device } from '@/stores/gantt'
import { useMobileTenantStore } from '@/stores/tenant'

const ganttStore = useGanttStore()
const tenantStore = useMobileTenantStore()
const canWrite = computed(() => tenantStore.currentWarehouseId !== 'all')

type LifecycleFilter =
  | 'all'
  | 'active'
  | 'sold'
  | 'decommissioned'
  | 'damaged'
  | 'retired'

const activeTab = ref<LifecycleFilter>('all')

const LIFECYCLE_LABELS: Record<string, string> = {
  active:          '使用中',
  sold:            '已售出',
  damaged:         '已损坏',
  decommissioned:  '已停用',
  retired:         '已退役',
}

const lifecycleBadgeType = (lifecycle: string) => {
  switch (lifecycle) {
    case 'active':         return 'success'
    case 'sold':           return 'warning'
    case 'damaged':        return 'danger'
    case 'decommissioned': return 'danger'
    case 'retired':        return 'default'
    default:               return 'default'
  }
}

// 所有设备（包含 accessory）
const allDevices = computed(() => ganttStore.devices)

const filteredDevices = computed(() => {
  if (activeTab.value === 'all') return allDevices.value.filter(d => !d.is_accessory)
  return allDevices.value.filter(
    d => !d.is_accessory && d.lifecycle_status === activeTab.value
  )
})

const targetDevice = ref<Device | null>(null)
const showLifecycleSheet = ref(false)

const lifecycleActions = [
  { name: '🟢 使用中',  value: 'active' },
  { name: '💰 已售出',  value: 'sold' },
  { name: '🔧 已损坏',  value: 'damaged' },
  { name: '⛔ 已停用',  value: 'decommissioned' },
  { name: '📦 已退役',  value: 'retired' },
]

const openLifecyclePicker = (device: Device) => {
  try {
    const warehouseId = tenantStore.requireConcreteWarehouse()
    if (device.warehouse_id !== warehouseId) {
      throw new Error('记录不属于当前仓库')
    }
  } catch (error: any) {
    showToast({ message: error.message, type: 'fail' })
    return
  }
  targetDevice.value = device
  showLifecycleSheet.value = true
}

const onLifecycleSelect = async (action: { name: string; value: string }) => {
  if (!targetDevice.value) return
  showLifecycleSheet.value = false
  try {
    const warehouseId = tenantStore.requireConcreteWarehouse()
    if (targetDevice.value.warehouse_id !== warehouseId) {
      throw new Error('记录不属于当前仓库')
    }
    await ganttStore.updateDeviceLifecycle(targetDevice.value.id, action.value)
    showToast({ message: `已更新为${action.name}`, type: 'success' })
  } catch (e: any) {
    showToast({ message: e.message || '更新失败', type: 'fail' })
  }
}

let reloadGeneration = 0
const reloadForWarehouse = async () => {
  const generation = ++reloadGeneration
  ganttStore.devices = []
  ganttStore.rentals = []
  targetDevice.value = null
  showLifecycleSheet.value = false
  await tenantStore.initialize()
  if (generation !== reloadGeneration) return
  await ganttStore.loadData()
}

onMounted(() => {
  void reloadForWarehouse()
})

watch(
  () => tenantStore.currentWarehouseId,
  () => { void reloadForWarehouse() },
  { flush: 'sync' },
)
</script>

<style scoped>
.device-status-view {
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: #f5f5f5;
}

.device-list {
  flex: 1;
  overflow-y: auto;
  -webkit-overflow-scrolling: touch;
  padding: 8px 12px;
}

.device-card {
  background: #fff;
  border-radius: 8px;
  margin-bottom: 8px;
  padding: 12px;
}

.device-main {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.device-info {
  flex: 1;
  min-width: 0;
}

.device-name {
  font-size: 14px;
  font-weight: 600;
  color: #333;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.device-sn {
  font-size: 11px;
  color: #999;
  margin-top: 2px;
}

.device-model {
  font-size: 11px;
  color: #666;
  margin-top: 1px;
}

.device-badges {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 4px;
  flex-shrink: 0;
  margin-left: 12px;
}

.status-badge,
.lifecycle-badge {
  cursor: pointer;
  font-size: 11px;
}

.lifecycle-badge.is-read-only {
  cursor: default;
  opacity: 0.7;
}

.loading-center {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}
</style>
