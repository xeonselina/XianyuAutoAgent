<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { showConfirmDialog, showSuccessToast } from 'vant'

import { updateRelayCase } from '@/api/relayCases'
import type { RelayCase, RelayCaseStatus } from '@/types/relayCase'

const props = defineProps<{
  modelValue: boolean
  relayCase: RelayCase | null
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  saved: []
}>()

const statuses: Array<{ value: RelayCaseStatus; label: string }> = [
  { value: 'pending', label: '待处理' },
  { value: 'notified', label: '已通知' },
  { value: 'agreed', label: '已同意' },
  { value: 'shipped', label: '已寄出' },
  { value: 'completed', label: '已完成' },
]

const statusOrder: Record<RelayCaseStatus, number> = {
  pending: 0,
  notified: 1,
  agreed: 2,
  shipped: 3,
  completed: 4,
}

const targetStatus = ref<RelayCaseStatus>('pending')
const trackingNumber = ref('')
const errorMessage = ref('')
const saving = ref(false)

const needsTracking = computed(
  () => targetStatus.value === 'shipped' || targetStatus.value === 'completed',
)

watch(
  () => [props.modelValue, props.relayCase] as const,
  () => {
    if (!props.modelValue || !props.relayCase) return
    targetStatus.value = props.relayCase.status
    trackingNumber.value = props.relayCase.tracking.number || ''
    errorMessage.value = ''
  },
  { immediate: true },
)

function close() {
  emit('update:modelValue', false)
}

function selectStatus(status: RelayCaseStatus) {
  targetStatus.value = status
  errorMessage.value = ''
}

async function save() {
  const relayCase = props.relayCase
  if (!relayCase) return
  errorMessage.value = ''

  if (needsTracking.value && !trackingNumber.value.trim()) {
    errorMessage.value = '请输入顺丰运单号'
    return
  }

  if (statusOrder[targetStatus.value] < statusOrder[relayCase.status]) {
    try {
      await showConfirmDialog({
        title: '确认回退状态',
        message: '回退至“已同意”之前会同步删除接力绑定，确定继续吗？',
      })
    } catch {
      return
    }
  }

  saving.value = true
  try {
    await updateRelayCase(relayCase.predecessor.id, relayCase.successor.id, {
      status: targetStatus.value,
      sf_tracking_number: needsTracking.value ? trackingNumber.value.trim() : undefined,
    })
    showSuccessToast('接力状态已更新')
    emit('saved')
    close()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '保存失败'
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <van-action-sheet
    :show="modelValue"
    title="维护接力状态"
    close-on-popstate
    @update:show="$emit('update:modelValue', $event)"
    @close="close"
  >
    <div v-if="relayCase" class="status-sheet">
      <div v-if="relayCase.schedule_changed" class="schedule-notice">
        档期已变化，此记录会保留，但不能重新进入“已同意”
      </div>

      <div class="pair-summary">
        <strong>{{ relayCase.predecessor.buyer_id || '-' }}</strong>
        <span>寄给</span>
        <strong>{{ relayCase.successor.buyer_id || '-' }}</strong>
      </div>

      <div class="status-grid">
        <button
          v-for="status in statuses"
          :key="status.value"
          type="button"
          class="status-option"
          :class="{ active: targetStatus === status.value }"
          :disabled="relayCase.schedule_changed && status.value === 'agreed' && relayCase.status !== 'agreed'"
          :data-testid="`relay-status-${status.value}`"
          @click="selectStatus(status.value)"
        >
          {{ status.label }}
        </button>
      </div>

      <label v-if="needsTracking" class="tracking-field">
        <span>顺丰运单号</span>
        <input
          v-model="trackingNumber"
          data-testid="relay-tracking-input"
          type="text"
          inputmode="text"
          placeholder="请输入顺丰运单号"
          @input="errorMessage = ''"
        >
      </label>

      <div v-if="errorMessage" class="error-message" role="alert">
        {{ errorMessage }}
      </div>

      <van-button
        block
        type="primary"
        :loading="saving"
        data-testid="save-relay-status"
        class="save-button"
        @click="save"
      >
        保存
      </van-button>
    </div>
  </van-action-sheet>
</template>

<style scoped>
.status-sheet {
  padding: 4px 16px calc(20px + env(safe-area-inset-bottom));
}

.schedule-notice,
.error-message {
  padding: 10px 12px;
  margin-bottom: 12px;
  border-radius: 8px;
  font-size: 13px;
}

.schedule-notice {
  color: #ed6a0c;
  background: #fff7e8;
}

.error-message {
  color: #ee0a24;
  background: #fff1f0;
}

.pair-summary {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  margin: 8px 0 16px;
}

.pair-summary span {
  color: #969799;
}

.status-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 9px;
}

.status-option {
  min-height: 44px;
  border: 1px solid #dcdee0;
  border-radius: 8px;
  background: #fff;
  color: #323233;
  font-size: 14px;
}

.status-option.active {
  border-color: #1989fa;
  color: #1989fa;
  background: #edf7ff;
  font-weight: 600;
}

.status-option:disabled {
  opacity: 0.4;
}

.tracking-field {
  display: block;
  margin-top: 16px;
  font-size: 13px;
}

.tracking-field span {
  display: block;
  margin-bottom: 6px;
  color: #646566;
}

.tracking-field input {
  width: 100%;
  min-height: 44px;
  padding: 0 12px;
  border: 1px solid #dcdee0;
  border-radius: 8px;
  outline: none;
  font-size: 16px;
}

.tracking-field input:focus {
  border-color: #1989fa;
}

.save-button {
  min-height: 46px;
  margin-top: 18px;
}
</style>
