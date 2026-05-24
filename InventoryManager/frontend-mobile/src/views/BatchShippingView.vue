<template>
  <div class="batch-view">
    <!-- 导航栏 -->
    <van-nav-bar title="批量发货" :border="false">
      <template #right>
        <van-button size="small" plain icon="filter-o" @click="filterSheetVisible = true">筛选</van-button>
      </template>
    </van-nav-bar>

    <!-- 日期筛选栏 -->
    <div class="filter-bar">
      <div class="date-range-row">
        <van-field
          v-model="startDateText"
          readonly
          clickable
          label=""
          placeholder="开始日期"
          class="date-field"
          @click="showStartDatePicker = true"
        />
        <span class="date-sep">至</span>
        <van-field
          v-model="endDateText"
          readonly
          clickable
          label=""
          placeholder="结束日期"
          class="date-field"
          @click="showEndDatePicker = true"
        />
        <van-button type="primary" size="small" @click="onQuery">查询</van-button>
      </div>
      <div class="stats-row">
        <span>共 {{ filteredRentals.length }} 单</span>
        <van-button size="mini" plain @click="toggleSelectAll">
          {{ allSelected ? '取消全选' : '全选' }}
        </van-button>
      </div>
    </div>

    <!-- 卡片列表 -->
    <div class="card-list" v-if="!loading">
      <van-empty v-if="!filteredRentals.length" description="暂无发货单" />
      <BatchShippingCard
        v-for="rental in filteredRentals"
        :key="rental.id"
        :rental="rental"
        v-model="checkedIds[rental.id]"
      />
    </div>

    <div class="loading-center" v-else>
      <van-loading color="#409eff" />
    </div>

    <!-- 底部操作栏 -->
    <div class="bottom-action-bar" v-if="selectedCount > 0">
      <van-button
        type="primary"
        block
        size="normal"
        :loading="scheduling"
        @click="showScheduleTimePicker = true"
      >预约发货 ({{ selectedCount }})</van-button>
      <van-button
        type="default"
        block
        size="normal"
        :loading="printing"
        @click="onPrint"
      >打印面单 ({{ selectedCount }})</van-button>
    </div>

    <!-- 开始日期选择器 -->
    <van-popup v-model:show="showStartDatePicker" position="bottom" round>
      <van-date-picker
        v-model="startDateParts"
        title="选择发货日期（起）"
        @confirm="onStartDateConfirm"
        @cancel="showStartDatePicker = false"
      />
    </van-popup>

    <!-- 结束日期选择器 -->
    <van-popup v-model:show="showEndDatePicker" position="bottom" round>
      <van-date-picker
        v-model="endDateParts"
        title="选择发货日期（止）"
        @confirm="onEndDateConfirm"
        @cancel="showEndDatePicker = false"
      />
    </van-popup>

    <!-- 预约发货时间选择器 -->
    <van-popup v-model:show="showScheduleTimePicker" position="bottom" round>
      <van-date-picker
        v-model="scheduleTimeParts"
        title="选择预约发货日期"
        @confirm="onScheduleTimeConfirm"
        @cancel="showScheduleTimePicker = false"
      />
    </van-popup>

    <!-- 状态筛选 ActionSheet -->
    <van-action-sheet
      v-model:show="filterSheetVisible"
      title="状态筛选"
      :actions="filterActions"
      @select="onFilterSelect"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, reactive } from 'vue'
import { showToast, showDialog } from 'vant'
import dayjs from 'dayjs'
import axios from 'axios'
import type { Rental } from '@/stores/gantt'
import BatchShippingCard from '@/components/BatchShippingCard.vue'

const loading = ref(false)
const scheduling = ref(false)
const printing = ref(false)
const filterSheetVisible = ref(false)
const showStartDatePicker = ref(false)
const showEndDatePicker = ref(false)
const showScheduleTimePicker = ref(false)

// 默认：今天 → 明天
const startDate = ref(dayjs().format('YYYY-MM-DD'))
const endDate = ref(dayjs().add(1, 'day').format('YYYY-MM-DD'))

const startDateText = ref(startDate.value)
const endDateText = ref(endDate.value)

// van-date-picker 需要 [yyyy, MM, DD] 数组
const startDateParts = ref(startDate.value.split('-'))
const endDateParts = ref(endDate.value.split('-'))

// 预约发货时间（默认明天上午10点）
const scheduledTime = ref(dayjs().add(1, 'day').format('YYYY-MM-DD') + 'T10:00:00')
const scheduleTimeParts = ref([
  dayjs().add(1, 'day').format('YYYY'),
  dayjs().add(1, 'day').format('MM'),
  dayjs().add(1, 'day').format('DD')
])

const statusFilter = ref<string>('all')
const rentals = ref<Rental[]>([])
const checkedIds = reactive<Record<number, boolean>>({})

const filteredRentals = computed(() => {
  if (statusFilter.value === 'all') return rentals.value
  return rentals.value.filter(r => r.status === statusFilter.value)
})

const selectedIds = computed(() => {
  return Object.entries(checkedIds)
    .filter(([, v]) => v)
    .map(([id]) => Number(id))
})

const selectedCount = computed(() => selectedIds.value.length)
const allSelected = computed(() =>
  filteredRentals.value.length > 0 &&
  filteredRentals.value.every(r => checkedIds[r.id])
)

const filterActions = [
  { name: '全部', value: 'all' },
  { name: '待发货', value: 'not_shipped' },
  { name: '已预约', value: 'scheduled_for_shipping' }
]

const onFilterSelect = (action: any) => {
  statusFilter.value = action.value
  filterSheetVisible.value = false
}

const onStartDateConfirm = ({ selectedValues }: any) => {
  startDate.value = selectedValues.join('-')
  startDateText.value = startDate.value
  startDateParts.value = selectedValues
  showStartDatePicker.value = false
}

const onEndDateConfirm = ({ selectedValues }: any) => {
  endDate.value = selectedValues.join('-')
  endDateText.value = endDate.value
  endDateParts.value = selectedValues
  showEndDatePicker.value = false
}

const onScheduleTimeConfirm = ({ selectedValues }: any) => {
  const dateStr = selectedValues.join('-')
  scheduledTime.value = dateStr + 'T10:00:00'
  scheduleTimeParts.value = selectedValues
  showScheduleTimePicker.value = false
  onSchedule()
}

const onQuery = async () => {
  loading.value = true
  // 清空选中状态
  Object.keys(checkedIds).forEach(k => { checkedIds[Number(k)] = false })
  try {
    const res = await axios.get('/api/rentals/by-ship-date', {
      params: { start_date: startDate.value, end_date: endDate.value }
    })
    if (res.data.success) {
      rentals.value = res.data.data?.rentals || []
    } else {
      showToast({ message: res.data.error || '查询失败', type: 'fail' })
    }
  } catch (e: any) {
    showToast({ message: e.message || '网络错误', type: 'fail' })
  } finally {
    loading.value = false
  }
}

const toggleSelectAll = () => {
  const shouldSelect = !allSelected.value
  filteredRentals.value.forEach(r => {
    if (!['shipped', 'returned', 'completed'].includes(r.status)) {
      checkedIds[r.id] = shouldSelect
    }
  })
}

const onSchedule = async () => {
  scheduling.value = true
  try {
    const res = await axios.post('/api/shipping-batch/schedule', {
      rental_ids: selectedIds.value,
      scheduled_time: scheduledTime.value
    })
    if (res.data.success) {
      showToast({ message: '预约发货成功', type: 'success' })
      await onQuery()
    } else {
      showToast({ message: res.data.error || '预约失败', type: 'fail' })
    }
  } catch (e: any) {
    showToast({ message: e.message || '网络错误', type: 'fail' })
  } finally {
    scheduling.value = false
  }
}

const onPrint = async () => {
  printing.value = true
  try {
    const res = await axios.post('/api/shipping-batch/print-waybills', { rental_ids: selectedIds.value })
    if (res.data.success) {
      showToast({ message: '打印任务已提交', type: 'success' })
    } else {
      showToast({ message: res.data.error || '打印失败', type: 'fail' })
    }
  } catch (e: any) {
    showToast({ message: e.message || '网络错误', type: 'fail' })
  } finally {
    printing.value = false
  }
}

onMounted(() => {
  onQuery()
})
</script>

<style scoped>
.batch-view {
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: #f7f8fa;
}

.filter-bar {
  background: #fff;
  padding: 8px 16px;
  border-bottom: 1px solid #eee;
  flex-shrink: 0;
}

.date-range-row {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 6px;
}

.date-field {
  flex: 1;
  padding: 0;
  background: #f7f8fa;
  border-radius: 6px;
}

:deep(.date-field .van-field__control) {
  font-size: 13px;
}

.date-sep {
  font-size: 12px;
  color: #666;
  flex-shrink: 0;
}

.stats-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 13px;
  color: #666;
}

.card-list {
  flex: 1;
  overflow-y: auto;
  -webkit-overflow-scrolling: touch;
}

.loading-center {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}

.bottom-action-bar {
  display: flex;
  gap: 12px;
  padding: 10px 16px;
  background: #fff;
  border-top: 1px solid #eee;
  flex-shrink: 0;
  position: relative;
  z-index: 100;
}

.bottom-action-bar .van-button {
  flex: 1;
}
</style>
