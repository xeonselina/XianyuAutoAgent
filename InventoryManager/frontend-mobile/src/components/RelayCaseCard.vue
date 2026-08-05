<script setup lang="ts">
import type { RelayAccessory, RelayCase, RelayCaseStatus } from '@/types/relayCase'

defineProps<{ relayCase: RelayCase }>()

defineEmits<{
  maintain: [relayCase: RelayCase]
  refresh: [relayCase: RelayCase]
}>()

const statusLabels: Record<RelayCaseStatus, string> = {
  pending: '待处理',
  notified: '已通知',
  agreed: '已同意',
  shipped: '已寄出',
  completed: '已完成',
}

const statusTypes: Record<RelayCaseStatus, 'default' | 'primary' | 'warning' | 'success'> = {
  pending: 'default',
  notified: 'primary',
  agreed: 'warning',
  shipped: 'primary',
  completed: 'success',
}

const lensLabels: Record<string, string> = {
  lens_400mm: '400MM 镜头',
  lens_200mm: '200MM 镜头',
  lens_dual: '双镜头',
  bare: '裸机',
}

function lensText(value: string | null) {
  return value ? (lensLabels[value] || value) : '未填写镜头'
}

function accessoryText(accessories: RelayAccessory[]) {
  return accessories.length ? accessories.map((item) => item.name).join('、') : '无附件'
}
</script>

<template>
  <article class="relay-card" data-testid="relay-card">
    <header class="card-header">
      <div class="device-title">
        <strong>{{ relayCase.device.model_display_name || relayCase.device.model || '-' }}</strong>
        <span>{{ relayCase.device.name || '' }}</span>
      </div>
      <div class="status-area">
        <van-tag :type="statusTypes[relayCase.status]">
          {{ statusLabels[relayCase.status] }}
        </van-tag>
        <span v-if="relayCase.schedule_changed" class="schedule-warning">档期已变化</span>
      </div>
    </header>

    <div class="equipment-row">
      <div><b>前单：</b>{{ lensText(relayCase.lens_combo) }} · {{ accessoryText(relayCase.accessories) }}</div>
      <div><b>后单：</b>{{ lensText(relayCase.successor_lens_combo) }} · {{ accessoryText(relayCase.successor_accessories) }}</div>
    </div>

    <section class="route-section">
      <div class="customer-block">
        <div class="customer-heading">
          <strong>{{ relayCase.predecessor.buyer_id || '-' }}</strong>
          <span>{{ relayCase.predecessor.customer_name || '-' }}</span>
        </div>
        <div>{{ relayCase.predecessor.start_date }} → {{ relayCase.predecessor.end_date }}</div>
        <a :href="`tel:${relayCase.predecessor.customer_phone || ''}`">
          {{ relayCase.predecessor.customer_phone || '-' }}
        </a>
        <div class="address">{{ relayCase.predecessor.destination || '-' }}</div>
      </div>

      <div class="route-arrow" aria-hidden="true">→</div>

      <div class="customer-block successor">
        <div class="customer-heading">
          <strong>{{ relayCase.successor.buyer_id || '-' }}</strong>
          <span>{{ relayCase.successor.customer_name || '-' }}</span>
        </div>
        <div>{{ relayCase.successor.start_date }} → {{ relayCase.successor.end_date }}</div>
        <a :href="`tel:${relayCase.successor.customer_phone || ''}`">
          {{ relayCase.successor.customer_phone || '-' }}
        </a>
        <div class="address">{{ relayCase.successor.destination || '-' }}</div>
      </div>
    </section>

    <div class="handoff-dates">
      <div><span>前单应寄出</span><strong>{{ relayCase.planned_ship_date }}</strong></div>
      <van-tag type="danger" plain>重叠 {{ relayCase.overlap_days }} 天</van-tag>
      <div class="receive-date"><span>后单应收货</span><strong>{{ relayCase.planned_receive_date }}</strong></div>
    </div>

    <div class="tracking-row">
      <div v-if="relayCase.tracking.number" class="tracking-copy">
        <strong>{{ relayCase.tracking.number }}</strong>
        <span>{{ relayCase.tracking.summary || relayCase.tracking.status || '暂无物流状态' }}</span>
      </div>
      <span v-else class="muted">尚未录入顺丰运单</span>
      <van-button
        v-if="relayCase.case_id && relayCase.tracking.number"
        size="small"
        plain
        type="primary"
        @click="$emit('refresh', relayCase)"
      >
        刷新物流
      </van-button>
    </div>

    <van-button
      block
      type="primary"
      plain
      class="maintain-button"
      data-testid="relay-maintain"
      @click="$emit('maintain', relayCase)"
    >
      维护接力状态
    </van-button>
  </article>
</template>

<style scoped>
.relay-card {
  padding: 14px;
  margin-bottom: 12px;
  border: 1px solid #ebedf0;
  border-radius: 12px;
  background: #fff;
  box-shadow: 0 2px 10px rgb(0 0 0 / 4%);
  color: #323233;
  font-size: 12px;
}

.card-header,
.status-area,
.handoff-dates,
.tracking-row,
.customer-heading {
  display: flex;
  align-items: center;
}

.card-header,
.tracking-row {
  justify-content: space-between;
  gap: 10px;
}

.device-title strong {
  font-size: 17px;
}

.device-title span,
.customer-heading span {
  margin-left: 6px;
  color: #646566;
}

.status-area {
  flex-direction: column;
  align-items: flex-end;
  gap: 3px;
}

.schedule-warning {
  color: #ed6a0c;
  font-size: 10px;
}

.equipment-row {
  padding: 9px 10px;
  margin-top: 10px;
  border-radius: 8px;
  background: #f7f8fa;
  line-height: 20px;
}

.route-section {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 28px minmax(0, 1fr);
  gap: 4px;
  padding: 12px 0;
}

.customer-block {
  min-width: 0;
  line-height: 19px;
}

.customer-block a {
  color: #1989fa;
  text-decoration: none;
}

.successor {
  text-align: right;
}

.successor .customer-heading {
  justify-content: flex-end;
}

.route-arrow {
  align-self: center;
  color: #1989fa;
  font-size: 22px;
  font-weight: 700;
  text-align: center;
}

.address {
  overflow-wrap: anywhere;
  color: #646566;
}

.handoff-dates {
  justify-content: space-between;
  gap: 6px;
  padding: 10px;
  border-top: 1px solid #f2f3f5;
  border-bottom: 1px solid #f2f3f5;
}

.handoff-dates div {
  display: flex;
  flex-direction: column;
}

.handoff-dates span,
.tracking-copy span,
.muted {
  color: #969799;
}

.receive-date {
  text-align: right;
}

.tracking-row {
  min-height: 52px;
  padding: 8px 0;
}

.tracking-copy {
  display: flex;
  min-width: 0;
  flex-direction: column;
}

.tracking-copy strong {
  color: #1989fa;
}

.tracking-copy span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.maintain-button {
  min-height: 44px;
}
</style>
