<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import dayjs from 'dayjs'
import { showSuccessToast } from 'vant'

import {
  createManualRelayCase,
  listManualRelayOptions,
} from '@/api/relayCases'
import type { ManualRelayOption, ManualRelayRental } from '@/types/relayCase'
import { relayEquipmentWarningText } from '@/utils/relayEquipmentWarnings'

const props = defineProps<{ modelValue: boolean }>()
const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  saved: []
}>()

const loading = ref(false)
const saving = ref(false)
const options = ref<ManualRelayOption[]>([])
const selectedDeviceId = ref<number | null>(null)
const errorMessage = ref('')

const selectedOption = computed(() => options.value.find(
  option => option.device.id === selectedDeviceId.value,
) || null)

function close() {
  emit('update:modelValue', false)
}

function deviceLabel(option: ManualRelayOption) {
  const model = option.device.model_display_name || option.device.model || '-'
  return `${option.device.name || '-'} · ${model}`
}

function statusLabel(status: ManualRelayRental['status']) {
  return {
    shipped: '已寄出',
    returned: '已寄回',
    not_shipped: '待发货',
    scheduled_for_shipping: '预约发货',
  }[status]
}

function shipTime(value: string | null) {
  return value ? dayjs(value).format('MM-DD HH:mm') : '-'
}

async function loadOptions() {
  loading.value = true
  errorMessage.value = ''
  selectedDeviceId.value = null
  try {
    options.value = (await listManualRelayOptions()).items
  } catch (error) {
    options.value = []
    errorMessage.value = error instanceof Error ? error.message : '加载设备失败'
  } finally {
    loading.value = false
  }
}

async function confirm() {
  const option = selectedOption.value
  if (!option?.device.id || !option.can_create) return
  saving.value = true
  errorMessage.value = ''
  try {
    await createManualRelayCase(option.device.id)
    showSuccessToast('接力关系已建立')
    emit('saved')
    close()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '建立接力失败'
  } finally {
    saving.value = false
  }
}

watch(
  () => props.modelValue,
  isOpen => {
    if (isOpen) void loadOptions()
  },
  { immediate: true },
)
</script>

<template>
  <van-action-sheet
    :show="modelValue"
    title="标记设备接力"
    close-on-popstate
    class="manual-sheet"
    @update:show="$emit('update:modelValue', $event)"
    @close="close"
  >
    <div class="sheet-content">
      <p class="sheet-hint">选择一台设备，系统自动匹配当前 rental 和下一笔 rental。</p>

      <van-loading v-if="loading" class="loading-state" color="#1677ff" />
      <van-notice-bar
        v-else-if="errorMessage"
        color="#c41d1d"
        background="#fff1f0"
        wrapable
        :text="errorMessage"
      />
      <van-empty
        v-else-if="!options.length"
        description="暂无可标记接力的设备"
        :image-size="72"
      />
      <van-radio-group v-else v-model="selectedDeviceId">
        <van-cell-group inset title="设备">
          <van-cell
            v-for="option in options"
            :key="option.device.id || option.device.name || ''"
            clickable
            :title="deviceLabel(option)"
            :label="option.blocked_reason || '可建立接力'"
            :class="{ blocked: !option.can_create }"
            data-testid="manual-relay-device"
            @click="option.can_create && (selectedDeviceId = option.device.id)"
          >
            <template #right-icon>
              <van-radio
                :name="option.device.id"
                :disabled="!option.can_create"
              />
            </template>
          </van-cell>
        </van-cell-group>
      </van-radio-group>

      <template v-if="selectedOption">
        <div class="rental-flow">
          <section class="rental-card">
            <div>
              <strong>当前 rental #{{ selectedOption.predecessor.id }}</strong>
              <van-tag type="success">{{ statusLabel(selectedOption.predecessor.status) }}</van-tag>
            </div>
            <p>{{ selectedOption.predecessor.customer_name || '-' }}</p>
            <small>{{ selectedOption.predecessor.start_date }} → {{ selectedOption.predecessor.end_date }}</small>
            <small>寄出 {{ shipTime(selectedOption.predecessor.ship_out_time) }}</small>
          </section>
          <div class="flow-arrow">↓ 自动接力</div>
          <section class="rental-card successor">
            <div>
              <strong>下一笔 rental #{{ selectedOption.successor.id }}</strong>
              <van-tag type="primary">{{ statusLabel(selectedOption.successor.status) }}</van-tag>
            </div>
            <p>{{ selectedOption.successor.customer_name || '-' }}</p>
            <small>{{ selectedOption.successor.start_date }} → {{ selectedOption.successor.end_date }}</small>
            <small>寄出 {{ shipTime(selectedOption.successor.ship_out_time) }}</small>
          </section>
        </div>

        <van-notice-bar
          v-if="relayEquipmentWarningText(selectedOption)"
          color="#ad6800"
          background="#fffbe6"
          wrapable
          :text="relayEquipmentWarningText(selectedOption)"
        />
      </template>
    </div>

    <div class="sheet-footer">
      <span>确认后记录为“已同意”</span>
      <van-button
        type="primary"
        :disabled="!selectedOption?.can_create"
        :loading="saving"
        data-testid="confirm-manual-relay"
        @click="confirm"
      >
        确认接力
      </van-button>
    </div>
  </van-action-sheet>
</template>

<style scoped>
.manual-sheet {
  max-height: 88vh;
}

.sheet-content {
  max-height: 66vh;
  overflow-y: auto;
  padding: 0 0 16px;
}

.sheet-hint {
  padding: 0 16px;
  margin: 0 0 10px;
  color: #7d828b;
  font-size: 13px;
}

.loading-state {
  display: flex;
  justify-content: center;
  padding: 40px;
}

.blocked {
  opacity: 0.56;
}

.rental-flow {
  padding: 14px 16px;
}

.rental-card {
  padding: 13px;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  background: #f8fafc;
}

.rental-card.successor {
  border-color: #91caff;
  background: #eaf4ff;
}

.rental-card div {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.rental-card p {
  margin: 9px 0 4px;
}

.rental-card small {
  display: block;
  margin-top: 3px;
  color: #7d828b;
}

.flow-arrow {
  padding: 7px;
  color: #1677ff;
  font-size: 12px;
  text-align: center;
}

.sheet-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 16px calc(10px + env(safe-area-inset-bottom));
  border-top: 1px solid #eef0f2;
}

.sheet-footer span {
  color: #7d828b;
  font-size: 12px;
}

.sheet-footer :deep(.van-button) {
  min-width: 116px;
  min-height: 44px;
  border-radius: 9px;
}
</style>
