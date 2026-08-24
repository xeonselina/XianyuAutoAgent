<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import { updateRelayCase } from '@/api/relayCases'
import type { RelayCase, RelayCaseStatus } from '@/types/relayCase'

const props = defineProps<{
  modelValue: boolean
  relayCase: RelayCase | null
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  saved: [value: unknown]
}>()

const statusOptions: Array<{ value: RelayCaseStatus; label: string }> = [
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
const accessoryNote = ref('')
const validationError = ref('')
const saving = ref(false)

const showTrackingInput = computed(
  () => targetStatus.value === 'shipped' || targetStatus.value === 'completed',
)

watch(
  () => [props.modelValue, props.relayCase] as const,
  () => {
    if (!props.modelValue || !props.relayCase) return
    targetStatus.value = props.relayCase.status
    trackingNumber.value = props.relayCase.tracking.number || ''
    accessoryNote.value = props.relayCase.accessory_note || ''
    validationError.value = ''
  },
  { immediate: true },
)

function close() {
  emit('update:modelValue', false)
}

async function save() {
  const relayCase = props.relayCase
  if (!relayCase) return
  validationError.value = ''

  if (showTrackingInput.value && !trackingNumber.value.trim()) {
    validationError.value = '请输入顺丰运单号'
    return
  }

  if (statusOrder[targetStatus.value] < statusOrder[relayCase.status]) {
    try {
      await ElMessageBox.confirm(
        '回退状态会同步撤销后续节点；回退至“已同意”之前还会删除接力绑定。确定继续吗？',
        '确认回退状态',
        { type: 'warning', confirmButtonText: '确认回退' },
      )
    } catch {
      return
    }
  }

  saving.value = true
  try {
    const result = await updateRelayCase(
      relayCase.predecessor.id,
      relayCase.successor.id,
      {
        status: targetStatus.value,
        sf_tracking_number: showTrackingInput.value
          ? trackingNumber.value.trim()
          : undefined,
        accessory_note: accessoryNote.value.trim() || null,
      },
    )
    const xianyuSync = result.xianyu_sync
    if (xianyuSync?.attempted && xianyuSync.success) {
      ElMessage.success('接力状态已更新，已同步闲鱼')
    } else if (xianyuSync?.attempted) {
      ElMessage.warning(
        `接力已标记已寄出，但闲鱼上报失败：${xianyuSync.message || '未知错误'}`,
      )
    } else {
      ElMessage.success('接力状态已更新')
    }
    emit('saved', result)
    close()
  } catch (error) {
    validationError.value = error instanceof Error ? error.message : '保存失败'
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    title="维护接力状态"
    width="520px"
    destroy-on-close
    @close="close"
  >
    <template v-if="relayCase">
      <el-alert
        v-if="relayCase.schedule_changed"
        title="档期已变化：此记录会保留，但不能重新进入“已同意”"
        type="warning"
        :closable="false"
        show-icon
        class="schedule-alert"
      />

      <el-descriptions :column="1" border size="small" class="case-summary">
        <el-descriptions-item label="前单">
          {{ relayCase.predecessor.buyer_id || '-' }} ·
          {{ relayCase.predecessor.customer_name || '-' }}
        </el-descriptions-item>
        <el-descriptions-item label="后单">
          {{ relayCase.successor.buyer_id || '-' }} ·
          {{ relayCase.successor.customer_name || '-' }}
        </el-descriptions-item>
        <el-descriptions-item label="计划寄出 / 收货">
          {{ relayCase.planned_ship_date }} / {{ relayCase.planned_receive_date }}
        </el-descriptions-item>
      </el-descriptions>

      <el-form label-width="92px" class="status-form">
        <el-form-item label="接力状态">
          <el-select v-model="targetStatus" style="width: 100%">
            <el-option
              v-for="option in statusOptions"
              :key="option.value"
              :label="option.label"
              :value="option.value"
              :disabled="relayCase.schedule_changed && option.value === 'agreed' && relayCase.status !== 'agreed'"
            />
          </el-select>
        </el-form-item>
        <el-form-item v-if="showTrackingInput" label="顺丰运单号">
          <el-input
            v-model="trackingNumber"
            data-testid="tracking-number"
            clearable
            placeholder="请输入顺丰运单号"
            @input="validationError = ''"
          />
        </el-form-item>
        <el-form-item label="内部补寄备注">
          <el-input
            v-model="accessoryNote"
            data-testid="accessory-note"
            type="textarea"
            :rows="3"
            maxlength="500"
            show-word-limit
            placeholder="仅内部可见；附件不足时可记录线下补寄安排，不会创建第二运单"
            @input="validationError = ''"
          />
        </el-form-item>
      </el-form>

      <el-alert
        v-if="validationError"
        :title="validationError"
        type="error"
        :closable="false"
        show-icon
      />
    </template>

    <template #footer>
      <el-button @click="close">取消</el-button>
      <el-button
        type="primary"
        :loading="saving"
        data-testid="save-relay-status"
        @click="save"
      >
        保存
      </el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.schedule-alert,
.case-summary {
  margin-bottom: 18px;
}

.status-form {
  margin: 6px 0 4px;
}
</style>
