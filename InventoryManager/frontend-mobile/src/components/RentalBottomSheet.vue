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
      <div v-if="rental?.booking" style="padding:12px">
        <strong>同单已录 {{ rental.booking.recorded_quantity }}/{{ rental.booking.expected_quantity }} 台 · 已发 {{ rental.booking.shipped_quantity }} 台</strong>
        <div v-for="item in rental.booking.rentals" :key="item.id"><van-button v-if="item.id !== rental.id" size="mini" @click="router.push({ name: 'edit-rental', params: { id: item.id } }); visible = false">查看此台</van-button> R-{{ item.id }} · {{ item.device_name }} · {{ item.lens_combo === 'bare' ? '裸机' : item.lens_combo === 'lens_200mm' ? '200mm 镜头' : item.lens_combo === 'lens_dual' ? '双镜头' : '400mm 镜头' }}</div>
      </div>
      <van-cell-group v-if="rental?.booking?.expected_quantity === 2 && rental.booking.recorded_quantity === 1">
        <van-field v-model="reductionReason" label="减租原因" placeholder="客户只租一台的原因" />
        <van-field v-model="reductionAmount" label="订单总金额" type="number" placeholder="减租后的总金额" />
        <van-button block :loading="reducingBooking" @click="reduceBooking">确认只租 1 台</van-button>
      </van-cell-group>
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
        <van-button block type="primary" size="normal" :disabled="!canWrite" @click="onEdit">编辑</van-button>
        <van-button block type="danger" size="normal" :disabled="!canWrite" @click="onDelete" :loading="deleting">删除</van-button>
      </div>
    </div>
  </van-popup>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { showConfirmDialog, showToast } from 'vant'
import dayjs from 'dayjs'
import axios from 'axios'
import type { Rental } from '@/stores/gantt'
import { useGanttStore } from '@/stores/gantt'
import { useMobileTenantStore } from '@/stores/tenant'

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
const tenantStore = useMobileTenantStore()
const deleting = ref(false)
const reductionReason = ref('')
const reductionAmount = ref('')
const reducingBooking = ref(false)
const reduceBooking = async () => {
  if (!props.rental || reducingBooking.value) return
  try {
    const warehouseId = tenantStore.requireConcreteWarehouse()
    await showConfirmDialog({ title: '确认减租', message: '确认客户只租一台，并以所填金额作为订单总金额？' })
    reducingBooking.value = true
    await axios.post(`/api/rentals/${props.rental.id}/reduce-booking`, {
      warehouse_id: warehouseId, reason: reductionReason.value, total_amount: reductionAmount.value,
    })
    await ganttStore.loadData()
    showToast('已确认减租为一台')
    visible.value = false
  } catch (e: any) {
    if (e !== 'cancel' && e !== 'close') showToast(e.response?.data?.error || e.message || '减租失败')
  } finally { reducingBooking.value = false }
}

const canWrite = computed(() => tenantStore.currentWarehouseId !== 'all')

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
  returned:             { label: '已寄回',  color: '#7232dd' },
  completed:            { label: '已完成',  color: '#333' },
  cancelled:            { label: '已取消',  color: '#999' }
}

const statusLabel = (s: string) => STATUS_MAP[s]?.label ?? s
const statusColor = (s: string) => STATUS_MAP[s]?.color ?? '#999'

const onEdit = () => {
  if (!props.rental) return
  try {
    tenantStore.requireConcreteWarehouse()
  } catch (error: any) {
    showToast({ message: error.message, type: 'fail' })
    return
  }
  visible.value = false
  router.push({ name: 'edit-rental', params: { id: props.rental.id } })
}

const onDelete = async () => {
  if (!props.rental) return
  try {
    tenantStore.requireConcreteWarehouse()
  } catch (error: any) {
    showToast({ message: error.message, type: 'fail' })
    return
  }
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
