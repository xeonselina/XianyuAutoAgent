<template>
  <div
    class="card"
    :class="{ checked: modelValue, disabled: isDisabled, relay: isRelayShipping }"
    :title="isRelayShipping ? RELAY_SELECTION_REASON : undefined"
    data-testid="batch-shipping-card"
    :data-rental-id="rental.id"
  >
    <!-- 复选框 -->
    <div class="card-check">
      <van-checkbox
        :model-value="modelValue"
        :disabled="isDisabled"
        @update:model-value="$emit('update:modelValue', $event)"
      />
    </div>

    <!-- 卡片主体 -->
    <div class="card-body" @click="onBodyClick">
      <!-- 顶行：设备+租客+状态 -->
      <div class="card-top">
        <span class="device-customer">
          {{ rental.device?.name || '—' }} · {{ rental.customer_name }}
        </span>
        <span class="card-tags">
          <van-tag
            v-if="isRelayShipping"
            color="#ed6a0c"
            text-color="#fff"
            data-testid="relay-shipping-tag"
          >
            接力寄出
          </van-tag>
          <van-tag :color="statusColor(rental.status)" text-color="#fff">
            {{ statusLabel(rental.status) }}
          </van-tag>
        </span>
      </div>

      <!-- 信息行 -->
      <div class="card-meta">
        <span class="meta-item">
          <van-icon name="calendar-o" size="11" />
          {{ fmtDate(rental.ship_out_time) }}
        </span>
        <span class="meta-item">
          <van-icon name="location-o" size="11" />
          {{ truncate(rental.destination, 18) }}
        </span>
      </div>

      <!-- 运单行 -->
      <div class="card-tracking">
        <van-icon name="send-gift-o" size="11" />
        {{ rental.ship_out_tracking_no || '—' }}
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import dayjs from 'dayjs'
import { showToast } from 'vant'
import type { Rental } from '@/stores/gantt'

const props = defineProps<{
  rental: Rental
  modelValue: boolean
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', val: boolean): void
}>()

const RELAY_SELECTION_REASON = '接力订单由前一位客户直接寄出，不能批量发货'
const isShipped = computed(() => (
  ['shipped', 'returned', 'completed'].includes(props.rental.status)
))
const isRelayShipping = computed(() => Boolean(props.rental.is_relay_shipping))
const isDisabled = computed(() => isShipped.value || isRelayShipping.value)

const onBodyClick = () => {
  if (isRelayShipping.value) {
    showToast(RELAY_SELECTION_REASON)
    return
  }
  if (isShipped.value) return
  emit('update:modelValue', !props.modelValue)
}

const fmtDate = (dt: string | undefined) => dt ? dayjs(dt).format('M/DD') : '—'

const truncate = (s: string | undefined, n: number) => {
  if (!s) return '—'
  return s.length > n ? s.slice(0, n) + '…' : s
}

const STATUS_MAP: Record<string, { label: string; color: string }> = {
  not_shipped:           { label: '待发货',  color: '#ff976a' },
  scheduled_for_shipping: { label: '已预约', color: '#1989fa' },
  shipped:               { label: '已发货',  color: '#07c160' },
  returned:              { label: '已寄回',  color: '#7232dd' },
  completed:             { label: '已完成',  color: '#333' },
  cancelled:             { label: '已取消',  color: '#999' }
}
const statusLabel = (s: string) => STATUS_MAP[s]?.label ?? s
const statusColor = (s: string) => STATUS_MAP[s]?.color ?? '#999'
</script>

<style scoped>
.card {
  display: flex;
  align-items: center;
  padding: 10px 16px;
  background: #fff;
  border-bottom: 1px solid #f0f0f0;
  gap: 10px;
  transition: background 0.15s;
}

.card.checked {
  background: #f0f8ff;
}

.card.disabled {
  opacity: 0.6;
}

.card.relay {
  border-left: 3px solid #ed6a0c;
  background: #fff8f2;
}

.card-check {
  flex-shrink: 0;
}

.card-body {
  flex: 1;
  min-width: 0;
}

.card-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 4px;
}

.device-customer {
  font-size: 13px;
  font-weight: 500;
  color: #333;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
  margin-right: 8px;
}

.card-tags {
  display: flex;
  flex: none;
  gap: 4px;
}

.card-meta {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 2px;
}

.meta-item {
  display: flex;
  align-items: center;
  gap: 2px;
  font-size: 11px;
  color: #666;
}

.card-tracking {
  font-size: 11px;
  color: #999;
  display: flex;
  align-items: center;
  gap: 2px;
}
</style>
