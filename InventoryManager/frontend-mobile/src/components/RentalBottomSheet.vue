<template>
  <van-popup
    v-model:show="visible"
    position="bottom"
    round
    :style="{ maxHeight: '75vh' }"
    @closed="$emit('closed')"
  >
    <div class="sheet-container">
      <!-- 拖动把手 -->
      <div class="drag-handle" />

      <!-- 标题 -->
      <div class="sheet-title">
        {{ rental?.device?.name || '租赁详情' }}
      </div>

      <!-- 信息列表 -->
      <div class="info-list" v-if="rental">
        <div class="info-row">
          <span class="info-label">租客</span>
          <span class="info-value">{{ rental.customer_name || '—' }}</span>
        </div>
        <div class="info-row">
          <span class="info-label">发货日</span>
          <span class="info-value">{{ fmtDate(rental.ship_out_time) }}</span>
        </div>
        <div class="info-row">
          <span class="info-label">起租日</span>
          <span class="info-value">{{ rental.start_date || '—' }}</span>
        </div>
        <div class="info-row">
          <span class="info-label">还租日</span>
          <span class="info-value">{{ rental.end_date || '—' }}</span>
        </div>
        <div class="info-row">
          <span class="info-label">入库日</span>
          <span class="info-value">{{ fmtDate(rental.ship_in_time) }}</span>
        </div>
        <div class="info-row">
          <span class="info-label">地址</span>
          <span class="info-value address">{{ rental.destination || '—' }}</span>
        </div>
        <div class="info-row">
          <span class="info-label">运单号</span>
          <span class="info-value">{{ rental.ship_out_tracking_no || '—' }}</span>
        </div>
        <div class="info-row">
          <span class="info-label">状态</span>
          <span class="info-value">
            <van-tag :color="statusColor(rental.status)" text-color="#fff">
              {{ statusLabel(rental.status) }}
            </van-tag>
          </span>
        </div>
      </div>

      <!-- 操作按钮 -->
      <div class="action-bar">
        <van-button block type="primary" size="normal" @click="onEdit">编辑</van-button>
        <van-button block type="danger" size="normal" @click="onDelete" :loading="deleting">删除</van-button>
      </div>
    </div>
  </van-popup>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { showConfirmDialog, showToast } from 'vant'
import dayjs from 'dayjs'
import type { Rental } from '@/stores/gantt'
import { useGanttStore } from '@/stores/gantt'

const props = defineProps<{
  modelValue: boolean
  rental: Rental | null
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', val: boolean): void
  (e: 'closed'): void
  (e: 'deleted'): void
}>()

const router = useRouter()
const ganttStore = useGanttStore()
const deleting = ref(false)

const visible = ref(props.modelValue)
watch(() => props.modelValue, v => { visible.value = v })
watch(visible, v => emit('update:modelValue', v))

const fmtDate = (dt: string | undefined) => {
  if (!dt) return '—'
  return dayjs(dt).format('YYYY-MM-DD')
}

const STATUS_MAP: Record<string, { label: string; color: string }> = {
  not_shipped:          { label: '待发货',  color: '#ff976a' },
  scheduled_for_shipping: { label: '已预约', color: '#1989fa' },
  shipped:              { label: '已发货',  color: '#07c160' },
  returned:             { label: '已还租',  color: '#7232dd' },
  completed:            { label: '已完成',  color: '#333' },
  cancelled:            { label: '已取消',  color: '#999' }
}

const statusLabel = (s: string) => STATUS_MAP[s]?.label ?? s
const statusColor = (s: string) => STATUS_MAP[s]?.color ?? '#999'

const onEdit = () => {
  if (!props.rental) return
  visible.value = false
  router.push({ name: 'edit-rental', params: { id: props.rental.id } })
}

const onDelete = async () => {
  if (!props.rental) return
  try {
    await showConfirmDialog({
      title: '确认删除',
      message: `确定要删除该租赁记录吗？此操作不可撤销。`
    })
  } catch {
    return // 用户取消
  }

  deleting.value = true
  try {
    await ganttStore.deleteRental(props.rental.id)
    showToast('删除成功')
    visible.value = false
    emit('deleted')
  } catch (e: any) {
    showToast({ message: e.message || '删除失败', type: 'fail' })
  } finally {
    deleting.value = false
  }
}
</script>

<style scoped>
.sheet-container {
  padding: 0 16px 24px;
}

.drag-handle {
  width: 40px;
  height: 4px;
  background: #ddd;
  border-radius: 2px;
  margin: 8px auto 16px;
}

.sheet-title {
  font-size: 16px;
  font-weight: 600;
  color: #333;
  margin-bottom: 12px;
  text-align: center;
}

.info-list {
  background: #f7f8fa;
  border-radius: 8px;
  padding: 4px 12px;
  margin-bottom: 16px;
}

.info-row {
  display: flex;
  padding: 8px 0;
  border-bottom: 1px solid #eee;
  align-items: flex-start;
}

.info-row:last-child {
  border-bottom: none;
}

.info-label {
  font-size: 13px;
  color: #666;
  width: 52px;
  flex-shrink: 0;
}

.info-value {
  font-size: 13px;
  color: #333;
  flex: 1;
  word-break: break-all;
}

.info-value.address {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.action-bar {
  display: flex;
  gap: 12px;
}

.action-bar .van-button {
  flex: 1;
}
</style>
