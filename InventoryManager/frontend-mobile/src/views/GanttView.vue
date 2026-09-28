<template>
  <div class="gantt-view">
    <!-- 导航栏 -->
    <van-nav-bar title="甘特图" :border="false">
      <template #left>
        <van-button size="small" icon="arrow-left" @click="shiftWindow(-7)" plain />
        <span class="date-range-label">{{ windowLabel }}</span>
        <van-button size="small" icon="arrow" @click="shiftWindow(7)" plain />
      </template>
      <template #right>
        <van-button
          size="small"
          :type="selectedModel ? 'primary' : 'default'"
          plain
          style="margin-right: 6px"
          @click="showModelFilter = true"
        >{{ selectedModel || '筛选' }}</van-button>
        <van-button
          size="small"
          icon="search"
          plain
          style="margin-right: 4px"
          @click="router.push({ name: 'search' })"
        />
        <van-button
          size="small"
          icon="friends-o"
          plain
          style="margin-right: 4px"
          @click="router.push({ name: 'customer-history' })"
        />
        <van-button
          size="small"
          icon="setting-o"
          plain
          style="margin-right: 4px"
          @click="router.push({ name: 'device-status' })"
        />
        <van-button
          size="small"
          type="primary"
          icon="plus"
          @click="goCreate"
        >新建</van-button>
      </template>
    </van-nav-bar>

    <XianyuOrderAlertBar
      :snapshot="alertSnapshot"
      :loading="alertsLoading"
      :busy-rental-id="busyRentalId"
      @book="bookMissingOrder"
      @ignore="payload => ignoreAlert('order', payload)"
      @rental-ignore="payload => ignoreAlert('rental', payload)"
      @rental-action="handleRentalAlertAction"
      @refresh="refreshAlerts"
    />

    <!-- 甘特图表格 -->
    <GanttGrid
      :devices="filteredDevices"
      :rentals="ganttStore.rentals"
      :window-start="windowStart"
      :loading="ganttStore.loading"
      :daily-stats="dailyStats"
      @bar-click="openSheet"
    />

    <!-- 底部详情弹窗 -->
    <RentalBottomSheet
      v-model="sheetVisible"
      :rental="selectedRental"
      @deleted="onDeleted"
    />

    <!-- 型号筛选 action sheet -->
    <van-action-sheet
      v-model:show="showModelFilter"
      :actions="modelFilterActions"
      cancel-text="取消"
      @select="onModelSelect"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onActivated, onDeactivated, onUnmounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { showConfirmDialog, showToast } from 'vant'
import dayjs from 'dayjs'
import axios from 'axios'
import { useGanttStore } from '@/stores/gantt'
import type { Rental } from '@/stores/gantt'
import GanttGrid from '@/components/GanttGrid.vue'
import RentalBottomSheet from '@/components/RentalBottomSheet.vue'
import XianyuOrderAlertBar from '@/components/XianyuOrderAlertBar.vue'
import { useMobileTenantStore } from '@/stores/tenant'
import type { XianyuOrderAlertSnapshot, XianyuRentalAlertAction } from '@/types/xianyuOrderAlert'

const router = useRouter()
const ganttStore = useGanttStore()
const tenantStore = useMobileTenantStore()
const alertSnapshot = ref<XianyuOrderAlertSnapshot>({
  alerts: [], rental_alerts: [], count: 0, refreshing: false,
  sync: { last_success_at: null, last_error: null, is_stale: false },
})
const alertsLoading = ref(false)
const busyRentalId = ref<number>()
let alertTimer: ReturnType<typeof setInterval> | undefined
let alertReadId = 0
let alertMutationVersion = 0
let alertMutationCount = 0

const applyAlertResponse = (response: any) => {
  if (response.data?.success && response.data.data) alertSnapshot.value = response.data.data
}
const loadAlerts = async () => {
  if (alertMutationCount) return
  const readId = ++alertReadId
  const version = alertMutationVersion
  try {
    const response = await axios.get('/api/xianyu-order-alerts')
    if (readId === alertReadId && version === alertMutationVersion && !alertMutationCount) applyAlertResponse(response)
  } catch {
    if (readId === alertReadId && version === alertMutationVersion && !alertMutationCount) {
      alertSnapshot.value = {
        ...alertSnapshot.value,
        sync: { ...alertSnapshot.value.sync, last_error: '读取订单提醒失败，当前显示上次结果' },
      }
    }
  }
}
const mutateAlerts = async (request: () => Promise<any>, errorMessage: string) => {
  if (alertsLoading.value) return
  alertMutationCount += 1
  alertMutationVersion += 1
  alertsLoading.value = true
  try {
    applyAlertResponse(await request())
  } catch (error: any) {
    showToast({ message: error.response?.data?.message || errorMessage, type: 'fail' })
  } finally {
    alertMutationCount -= 1
    alertsLoading.value = false
  }
}
const refreshAlerts = () => mutateAlerts(
  () => axios.post('/api/xianyu-order-alerts/refresh'), '刷新订单提醒失败',
)
const ignoreAlert = (kind: 'order' | 'rental', payload: { shopId: number; orderNo: string; reason: string }) => mutateAlerts(
  () => axios.post(
    `/api/xianyu-order-alerts/${payload.shopId}/${encodeURIComponent(payload.orderNo)}/${kind === 'order' ? 'ignore' : 'rental-ignore'}`,
    { reason: payload.reason },
  ),
  kind === 'order' ? '忽略订单失败' : '忽略档期提醒失败',
)
const bookMissingOrder = (payload: { orderNo: string; shopId: number }) => {
  router.push({ name: 'create-rental', query: { orderNo: payload.orderNo, shopId: String(payload.shopId) } })
}
const handleRentalAlertAction = async (payload: XianyuRentalAlertAction) => {
  if (busyRentalId.value !== undefined) return
  busyRentalId.value = payload.rentalId
  try {
    await tenantStore.initialize()
    let rental = await ganttStore.getRentalById(payload.rentalId)
    if (!rental || rental.xianyu_order_no?.trim() !== payload.orderNo || rental.xianyu_shop_id !== payload.shopId) {
      showToast('档期已变更或不存在，请刷新提醒后重试')
      await loadAlerts()
      return
    }
    if (!['not_shipped', 'scheduled_for_shipping', 'shipped'].includes(rental.status)) {
      showToast('该档期已处理')
      await loadAlerts()
      return
    }
    if (!rental.warehouse_id) throw new Error('档期缺少仓库信息')
    tenantStore.selectWarehouse(rental.warehouse_id)
    await ganttStore.loadData()
    rental = await ganttStore.getRentalById(payload.rentalId)
    if (!rental || rental.warehouse_id !== tenantStore.currentWarehouseId
      || rental.xianyu_order_no?.trim() !== payload.orderNo || rental.xianyu_shop_id !== payload.shopId) {
      throw new Error('档期或仓库已变更，请刷新后重试')
    }
    if (!['not_shipped', 'scheduled_for_shipping', 'shipped'].includes(rental.status)) {
      showToast('该档期已处理')
      await loadAlerts()
      return
    }
    if (payload.action === 'delete' && rental.status !== 'shipped') {
      try {
        await showConfirmDialog({
          title: '确认删除',
          message: `确定删除 ${rental.customer_name} 的 ${rental.device?.name || '设备'} 档期（${rental.start_date} 至 ${rental.end_date}）吗？关联附件档期也会一并删除，此操作不可恢复。`,
          confirmButtonText: '确定删除',
          confirmButtonColor: '#ee0a24',
        })
      } catch { return }
      await ganttStore.deleteRental(rental.id)
      showToast({ message: '删除成功', type: 'success' })
      await Promise.all([loadAlerts(), fetchDailyStats()])
    } else {
      router.push({ name: 'edit-rental', params: { id: rental.id } })
    }
  } catch (error: any) {
    showToast({ message: error.message || '读取档期失败', type: 'fail' })
  } finally {
    busyRentalId.value = undefined
  }
}

// 窗口起始日期：今天 -2 天
const windowOffset = ref(0) // 以7天为单位的偏移
const windowStart = computed(() => {
  return dayjs().subtract(2, 'day').add(windowOffset.value * 7, 'day').format('YYYY-MM-DD')
})

const windowLabel = computed(() => {
  const start = dayjs(windowStart.value)
  const end = start.add(13, 'day')
  return `${start.format('M/D')}~${end.format('M/D')}`
})

const sheetVisible = ref(false)
const selectedRental = ref<Rental | null>(null)

// 每日统计数据
const dailyStats = ref<Record<string, { available_count: number; ship_out_count: number; accessory_ship_out_count: number }>>({})

const DAYS = 14
let statsGeneration = 0

const fetchDailyStats = async () => {
  const requestGeneration = ++statsGeneration
  dailyStats.value = {}
  try {
    await tenantStore.initialize()
    if (requestGeneration !== statsGeneration) return
    const warehouseId = tenantStore.currentWarehouseId
    const start = dayjs(windowStart.value)
    const dates = Array.from({ length: DAYS }, (_, i) => start.add(i, 'day').format('YYYY-MM-DD'))
    const response = await axios.get('/api/gantt/daily-stats', {
      params: {
        start_date: dates[0],
        end_date: dates[dates.length - 1],
        warehouse_id: warehouseId,
      },
    })
    const stats: typeof dailyStats.value = response.data?.success
      ? response.data.data?.stats || {}
      : {}
    if (
      requestGeneration === statsGeneration
      && warehouseId === tenantStore.currentWarehouseId
    ) dailyStats.value = stats
  } catch {
    // 新仓加载失败时保持空状态；过期请求不污染当前仓。
  }
}

const shiftWindow = (days: number) => {
  windowOffset.value += days / 7
  ganttStore.loadData()
  fetchDailyStats()
}

const openSheet = (rental: Rental) => {
  selectedRental.value = rental
  sheetVisible.value = true
}

const onDeleted = () => {
  ganttStore.loadData()
  fetchDailyStats()
  loadAlerts()
}

const goCreate = () => {
  router.push({ name: 'create-rental' })
}

// ── 型号筛选 ──────────────────────────────────────────
const selectedModel = ref<string | null>(null)
const showModelFilter = ref(false)

const availableModels = computed(() => {
  const models = new Set(ganttStore.availableDevices.map(d => d.model).filter(Boolean))
  return Array.from(models).sort()
})

const modelFilterActions = computed(() => [
  { name: '全部型号', value: null },
  ...availableModels.value.map(m => ({ name: m, value: m }))
])

const onModelSelect = (action: { name: string; value: string | null }) => {
  selectedModel.value = action.value
  showModelFilter.value = false
}

const filteredDevices = computed(() => {
  if (!selectedModel.value) return ganttStore.availableDevices
  return ganttStore.availableDevices.filter(d => d.model === selectedModel.value)
})

onMounted(() => {
  ganttStore.loadData()
  fetchDailyStats()
  loadAlerts()
  startAlertPolling()
})

let activatedOnce = false
const startAlertPolling = () => {
  if (!alertTimer) alertTimer = setInterval(loadAlerts, 60_000)
}
const stopAlertPolling = () => {
  if (alertTimer) clearInterval(alertTimer)
  alertTimer = undefined
}
onActivated(() => {
  if (activatedOnce) {
    ganttStore.loadData()
    fetchDailyStats()
    loadAlerts()
  }
  activatedOnce = true
  startAlertPolling()
})
onDeactivated(stopAlertPolling)
onUnmounted(stopAlertPolling)

watch(() => tenantStore.currentWarehouseId, () => {
  selectedRental.value = null
  sheetVisible.value = false
  dailyStats.value = {}
  ganttStore.loadData()
  fetchDailyStats()
}, { flush: 'sync' })
</script>

<style scoped>
.gantt-view {
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* 导航栏内布局 */
:deep(.van-nav-bar__left) {
  display: flex;
  align-items: center;
  gap: 4px;
}

.date-range-label {
  font-size: 12px;
  color: #333;
  white-space: nowrap;
}

/* 让甘特表格占满剩余高度 */
.gantt-view > :deep(.gantt-grid) {
  flex: 1;
  overflow: hidden;
}
</style>
