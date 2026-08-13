<script setup lang="ts">
import { ref } from 'vue'

import type { RelayAccessory, RelayCase, RelayCaseStatus } from '@/types/relayCase'
import { relayEquipmentWarningText } from '@/utils/relayEquipmentWarnings'

defineProps<{ relayCase: RelayCase }>()

defineEmits<{
  maintain: [relayCase: RelayCase]
  refresh: [relayCase: RelayCase]
}>()

const expanded = ref(false)

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
      <div class="deadline-block">
        <span>前单应寄出</span>
        <strong>{{ relayCase.planned_ship_date }}</strong>
        <small>后单 {{ relayCase.planned_receive_date }} 前收货</small>
      </div>
      <div class="header-meta">
        <van-tag :type="statusTypes[relayCase.status]" size="medium">
          {{ statusLabels[relayCase.status] }}
        </van-tag>
        <van-tag v-if="relayCase.source === 'manual'" plain type="primary">
          人工
        </van-tag>
        <span class="overlap">重叠 {{ relayCase.overlap_days }} 天</span>
      </div>
    </header>

    <div
      v-if="relayEquipmentWarningText(relayCase)"
      class="equipment-warning"
      data-testid="equipment-warning"
    >
      <span aria-hidden="true">⚠</span>
      <div>
        <strong>转寄配置需确认</strong>
        <p>{{ relayEquipmentWarningText(relayCase) }}</p>
      </div>
    </div>

    <div v-if="relayCase.schedule_changed" class="schedule-warning">
      <span aria-hidden="true">⚠</span> 档期已变化，请先核对后再操作
    </div>

    <section class="customer-flow">
      <div class="customer-mini">
        <span class="role-label">前单客户</span>
        <div class="customer-name">
          <strong>{{ relayCase.predecessor.buyer_id || '-' }}</strong>
          <span>{{ relayCase.predecessor.customer_name || '-' }}</span>
        </div>
        <a class="phone-link" :href="`tel:${relayCase.predecessor.customer_phone || ''}`">
          <van-icon name="phone-o" /> {{ relayCase.predecessor.customer_phone || '-' }}
        </a>
      </div>

      <div class="flow-arrow" aria-label="转寄给">→</div>

      <div class="customer-mini successor">
        <span class="role-label">后单客户</span>
        <div class="customer-name">
          <strong>{{ relayCase.successor.buyer_id || '-' }}</strong>
          <span>{{ relayCase.successor.customer_name || '-' }}</span>
        </div>
        <a class="phone-link" :href="`tel:${relayCase.successor.customer_phone || ''}`">
          <van-icon name="phone-o" /> {{ relayCase.successor.customer_phone || '-' }}
        </a>
      </div>
    </section>

    <section class="equipment-compare">
      <div class="device-heading">
        <van-icon name="photograph" />
        <strong>{{ relayCase.device.model_display_name || relayCase.device.model || '-' }}</strong>
        <span>{{ relayCase.device.name || '' }}</span>
      </div>
      <div class="compare-columns">
        <div>
          <span class="role-label">前单携带</span>
          <strong>{{ lensText(relayCase.lens_combo) }}</strong>
          <p>{{ accessoryText(relayCase.accessories) }}</p>
        </div>
        <div>
          <span class="role-label">后单需要</span>
          <strong>{{ lensText(relayCase.successor_lens_combo) }}</strong>
          <p>{{ accessoryText(relayCase.successor_accessories) }}</p>
        </div>
      </div>
    </section>

    <button
      type="button"
      class="details-toggle"
      data-testid="relay-expand-details"
      @click="expanded = !expanded"
    >
      {{ expanded ? '收起客户详情' : '查看地址与完整租期' }}
      <van-icon :name="expanded ? 'arrow-up' : 'arrow-down'" />
    </button>

    <section v-if="expanded" class="customer-details" data-testid="relay-card-details">
      <div>
        <span class="detail-title">前单</span>
        <p>{{ relayCase.predecessor.start_date }} → {{ relayCase.predecessor.end_date }}</p>
        <p>{{ relayCase.predecessor.destination || '地址未填写' }}</p>
      </div>
      <div>
        <span class="detail-title">后单</span>
        <p>{{ relayCase.successor.start_date }} → {{ relayCase.successor.end_date }}</p>
        <p>{{ relayCase.successor.destination || '地址未填写' }}</p>
      </div>
    </section>

    <section class="tracking-brief">
      <div v-if="relayCase.tracking.number" class="tracking-copy">
        <span class="role-label">顺丰运单</span>
        <strong>{{ relayCase.tracking.number }}</strong>
        <p>{{ relayCase.tracking.summary || relayCase.tracking.status || '暂无物流状态' }}</p>
      </div>
      <div v-else class="tracking-copy muted">
        <span class="role-label">顺丰运单</span>
        <p>尚未录入</p>
      </div>
    </section>

    <footer class="card-actions" data-testid="relay-card-actions">
      <van-button
        block
        plain
        type="primary"
        icon="logistics"
        :disabled="!relayCase.case_id || !relayCase.tracking.number"
        data-testid="relay-logistics"
        @click="$emit('refresh', relayCase)"
      >
        刷新物流
      </van-button>
      <van-button
        block
        type="primary"
        icon="edit"
        data-testid="relay-maintain"
        @click="$emit('maintain', relayCase)"
      >
        更新状态
      </van-button>
    </footer>
  </article>
</template>

<style scoped>
.relay-card {
  padding: 0;
  margin-bottom: 14px;
  overflow: hidden;
  border: 1px solid #e8eaed;
  border-radius: 14px;
  background: #fff;
  box-shadow: 0 4px 16px rgb(31 41 55 / 7%);
  color: #202124;
  font-size: 13px;
}

.card-header,
.customer-flow,
.device-heading,
.compare-columns,
.details-toggle,
.card-actions,
.customer-name,
.equipment-warning {
  display: flex;
  align-items: center;
}

.card-header {
  justify-content: space-between;
  gap: 12px;
  padding: 14px 14px 12px;
  border-bottom: 1px solid #f0f1f3;
}

.deadline-block,
.header-meta,
.customer-mini,
.tracking-copy {
  display: flex;
  flex-direction: column;
}

.deadline-block > span,
.role-label {
  color: #8a8f98;
  font-size: 11px;
}

.deadline-block > strong {
  margin: 2px 0;
  color: #d9480f;
  font-size: 20px;
  line-height: 24px;
}

.deadline-block small {
  color: #6b7280;
  font-size: 11px;
}

.header-meta {
  align-items: flex-end;
  gap: 6px;
}

.overlap {
  color: #d9480f;
  font-size: 11px;
  font-weight: 600;
}

.equipment-warning,
.schedule-warning {
  margin: 10px 12px 0;
  border: 1px solid #f0c36d;
  border-radius: 9px;
  color: #8a4b08;
  background: #fff7df;
}

.equipment-warning {
  gap: 8px;
  padding: 9px 10px;
}

.equipment-warning > span {
  flex: none;
  font-size: 20px;
}

.equipment-warning strong {
  font-size: 12px;
}

.equipment-warning p {
  margin: 2px 0 0;
  font-size: 11px;
  line-height: 16px;
}

.schedule-warning {
  padding: 8px 10px;
  font-size: 11px;
}

.customer-flow {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 30px minmax(0, 1fr);
  gap: 4px;
  padding: 14px;
}

.customer-mini {
  min-width: 0;
  gap: 5px;
}

.customer-name {
  min-width: 0;
  gap: 5px;
}

.customer-name strong {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 16px;
}

.customer-name span {
  overflow: hidden;
  color: #5f6368;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.successor {
  align-items: flex-end;
  text-align: right;
}

.phone-link {
  min-height: 32px;
  color: #1677ff;
  line-height: 32px;
  text-decoration: none;
  white-space: nowrap;
}

.flow-arrow {
  align-self: center;
  color: #1677ff;
  font-size: 25px;
  font-weight: 700;
  text-align: center;
}

.equipment-compare {
  margin: 0 12px;
  overflow: hidden;
  border: 1px solid #e8eaed;
  border-radius: 10px;
}

.device-heading {
  gap: 6px;
  padding: 8px 10px;
  border-bottom: 1px solid #e8eaed;
  background: #f7f8fa;
}

.device-heading strong {
  font-size: 14px;
}

.device-heading span {
  color: #73777f;
  font-size: 12px;
}

.compare-columns > div {
  min-width: 0;
  flex: 1;
  padding: 9px 10px;
}

.compare-columns > div + div {
  border-left: 1px solid #e8eaed;
  background: #fcfcfd;
}

.compare-columns strong {
  display: block;
  margin-top: 4px;
  font-size: 12px;
}

.compare-columns p {
  margin: 3px 0 0;
  overflow-wrap: anywhere;
  color: #646a73;
  font-size: 11px;
  line-height: 16px;
}

.details-toggle {
  width: calc(100% - 24px);
  min-height: 44px;
  justify-content: center;
  gap: 5px;
  padding: 0;
  margin: 5px 12px 0;
  border: 0;
  background: transparent;
  color: #5f6368;
  font-size: 12px;
}

.customer-details {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1px;
  margin: 0 12px 10px;
  overflow: hidden;
  border-radius: 8px;
  background: #e8eaed;
}

.customer-details > div {
  padding: 9px;
  background: #f7f8fa;
}

.detail-title {
  color: #1677ff;
  font-size: 11px;
  font-weight: 700;
}

.customer-details p {
  margin: 4px 0 0;
  overflow-wrap: anywhere;
  color: #5f6368;
  font-size: 11px;
  line-height: 16px;
}

.tracking-brief {
  padding: 10px 14px;
  border-top: 1px solid #f0f1f3;
}

.tracking-copy strong {
  margin-top: 2px;
  color: #1677ff;
  font-size: 14px;
}

.tracking-copy p {
  margin: 2px 0 0;
  overflow: hidden;
  color: #69707a;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 11px;
}

.muted p {
  color: #9aa0a6;
}

.card-actions {
  gap: 10px;
  padding: 10px 12px 12px;
  border-top: 1px solid #f0f1f3;
  background: #fbfcfd;
}

.card-actions :deep(.van-button) {
  min-height: 46px;
  flex: 1;
  border-radius: 9px;
}
</style>
