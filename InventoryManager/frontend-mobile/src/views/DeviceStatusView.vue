<template>
  <div class="device-status-view">
    <van-nav-bar
      title="设备状态管理"
      left-arrow
      @click-left="$router.back()"
      :border="false"
    />

    <!-- 在线/离线 tab 过滤 -->
    <van-tabs v-model:active="activeTab" sticky>
      <van-tab title="全部" name="all" />
      <van-tab title="在线" name="online" />
      <van-tab title="离线" name="offline" />
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
              <!-- 在线/离线 badge -->
              <van-tag
                :type="device.status === 'online' ? 'success' : 'default'"
                class="status-badge"
                @click="openStatusPicker(device)"
              >
                {{ device.status === 'online' ? '在线' : '离线' }}
              </van-tag>
              <!-- 生命周期 badge -->
              <van-tag
                :type="lifecycleBadgeType(device.lifecycle_status)"
                class="lifecycle-badge"
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

    <!-- 在线/离线 选择 -->
    <van-action-sheet
      v-model:show="showStatusSheet"
      title="修改使用状态"
      :actions="statusActions"
      cancel-text="取消"
      @select="onStatusSelect"
    />

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
import { ref, computed, onMounted } from 'vue'
import { showToast } from 'vant'
import { useGanttStore } from '@/stores/gantt'
import type { Device } from '@/stores/gantt'

const ganttStore = useGanttStore()

const activeTab = ref<'all' | 'online' | 'offline'>('all')

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
  return allDevices.value.filter(d => !d.is_accessory && d.status === activeTab.value)
})

// ── 在线/离线 picker ─────────────────────────────────
const showStatusSheet = ref(false)
const targetDevice = ref<Device | null>(null)

const statusActions = [
  { name: '在线', value: 'online', color: '#07c160' },
  { name: '离线', value: 'offline', color: '#999' },
]

const openStatusPicker = (device: Device) => {
  targetDevice.value = device
  showStatusSheet.value = true
}

const onStatusSelect = async (action: { name: string; value: string }) => {
  if (!targetDevice.value) return
  showStatusSheet.value = false
  try {
    await ganttStore.updateDeviceStatus(targetDevice.value.id, action.value)
    showToast({ message: `已设为${action.name}`, type: 'success' })
  } catch (e: any) {
    showToast({ message: e.message || '更新失败', type: 'fail' })
  }
}

// ── 生命周期 picker ──────────────────────────────────
const showLifecycleSheet = ref(false)

const lifecycleActions = [
  { name: '🟢 使用中',  value: 'active' },
  { name: '💰 已售出',  value: 'sold' },
  { name: '🔧 已损坏',  value: 'damaged' },
  { name: '⛔ 已停用',  value: 'decommissioned' },
  { name: '📦 已退役',  value: 'retired' },
]

const openLifecyclePicker = (device: Device) => {
  targetDevice.value = device
  showLifecycleSheet.value = true
}

const onLifecycleSelect = async (action: { name: string; value: string }) => {
  if (!targetDevice.value) return
  showLifecycleSheet.value = false
  try {
    await ganttStore.updateDeviceLifecycle(targetDevice.value.id, action.value)
    showToast({ message: `已更新为${action.name}`, type: 'success' })
  } catch (e: any) {
    showToast({ message: e.message || '更新失败', type: 'fail' })
  }
}

onMounted(() => {
  if (!ganttStore.devices.length) {
    ganttStore.loadData()
  }
})
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

.loading-center {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}
</style>
