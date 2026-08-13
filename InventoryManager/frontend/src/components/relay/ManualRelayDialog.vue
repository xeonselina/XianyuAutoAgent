<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import dayjs from 'dayjs'
import { ElMessage } from 'element-plus'

import {
  createManualRelayCase,
  listManualRelayOptions,
} from '@/api/relayCases'
import { relayEquipmentWarningText } from '@/utils/relayEquipmentWarnings'
import type { ManualRelayOption, ManualRelayRental } from '@/types/relayCase'

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

const lensLabels: Record<string, string> = {
  lens_400mm: '400MM 镜头',
  lens_200mm: '200MM 镜头',
  lens_dual: '双镜头',
  bare: '裸机',
}

function close() {
  emit('update:modelValue', false)
}

function rentalStatus(status: ManualRelayRental['status']) {
  return {
    shipped: '已寄出',
    returned: '已寄回',
    not_shipped: '待发货',
    scheduled_for_shipping: '预约发货',
  }[status]
}

function rentalPeriod(rental: ManualRelayRental) {
  return `${rental.start_date} → ${rental.end_date}`
}

function formatDateTime(value: string | null) {
  return value ? dayjs(value).format('YYYY-MM-DD HH:mm') : '-'
}

function lensText(value: string | null) {
  if (!value) return '未填写镜头'
  return lensLabels[value] || value
}

function optionLabel(option: ManualRelayOption) {
  const model = option.device.model_display_name || option.device.model || '-'
  const label = `${option.device.name || '-'} · ${model}`
  return option.blocked_reason ? `${label}（${option.blocked_reason}）` : label
}

async function loadOptions() {
  loading.value = true
  errorMessage.value = ''
  selectedDeviceId.value = null
  try {
    const response = await listManualRelayOptions()
    options.value = response.items
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
    ElMessage.success('接力关系已建立')
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
  <el-dialog
    :model-value="modelValue"
    title="标记设备接力"
    width="720px"
    destroy-on-close
    :close-on-click-modal="false"
    @close="close"
  >
    <p class="dialog-hint">选择设备，系统自动找出当前 rental 和下一笔 rental。</p>

    <el-form label-width="72px" v-loading="loading">
      <el-form-item label="设备">
        <el-select
          v-model="selectedDeviceId"
          filterable
          clearable
          placeholder="请选择设备"
          style="width: 100%"
          data-testid="manual-relay-device"
        >
          <el-option
            v-for="option in options"
            :key="option.device.id || option.device.name || ''"
            :label="optionLabel(option)"
            :value="option.device.id"
            :disabled="!option.can_create"
          />
        </el-select>
      </el-form-item>
    </el-form>

    <el-alert
      v-if="errorMessage"
      :title="errorMessage"
      type="error"
      :closable="false"
      show-icon
      class="feedback"
    />

    <el-empty
      v-else-if="!loading && options.length === 0"
      description="当前没有同时具备进行中 rental 和下一笔 rental 的设备"
      :image-size="72"
    />

    <template v-if="selectedOption">
      <div class="rental-flow">
        <section class="rental-card">
          <header>
            <strong>当前 rental</strong>
            <el-tag size="small" type="success">
              {{ rentalStatus(selectedOption.predecessor.status) }}
            </el-tag>
          </header>
          <h3>#{{ selectedOption.predecessor.id }} · {{ selectedOption.predecessor.customer_name || '-' }}</h3>
          <p>{{ rentalPeriod(selectedOption.predecessor) }}</p>
          <p>寄出：{{ formatDateTime(selectedOption.predecessor.ship_out_time) }}</p>
          <p>{{ selectedOption.predecessor.destination || '未填写地址' }}</p>
          <p>{{ lensText(selectedOption.lens_combo) }}</p>
        </section>

        <div class="flow-arrow" aria-hidden="true">→</div>

        <section class="rental-card next-card">
          <header>
            <strong>下一笔 rental</strong>
            <span>自动匹配</span>
          </header>
          <h3>#{{ selectedOption.successor.id }} · {{ selectedOption.successor.customer_name || '-' }}</h3>
          <p>{{ rentalPeriod(selectedOption.successor) }}</p>
          <p>寄出：{{ formatDateTime(selectedOption.successor.ship_out_time) }}</p>
          <p>{{ selectedOption.successor.destination || '未填写地址' }}</p>
          <p>{{ lensText(selectedOption.successor_lens_combo) }}</p>
        </section>
      </div>

      <el-alert
        v-if="relayEquipmentWarningText(selectedOption)"
        :title="relayEquipmentWarningText(selectedOption)"
        type="warning"
        :closable="false"
        show-icon
        class="feedback"
        data-testid="manual-relay-warning"
      />
    </template>

    <template #footer>
      <span class="footer-hint">确认后建立接力关系，并记录为“已同意”。</span>
      <el-button @click="close">取消</el-button>
      <el-button
        type="primary"
        :disabled="!selectedOption?.can_create"
        :loading="saving"
        data-testid="confirm-manual-relay"
        @click="confirm"
      >
        确认接力
      </el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.dialog-hint {
  margin: -4px 0 18px;
  color: #6b7280;
}

.rental-flow {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 36px minmax(0, 1fr);
  align-items: stretch;
  gap: 10px;
  margin-top: 18px;
}

.rental-card {
  padding: 14px;
  border: 1px solid #dcdfe6;
  border-radius: 7px;
  background: #f7f8fa;
}

.next-card {
  border-color: #409eff;
  background: #ecf5ff;
}

.rental-card header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  color: #6b7280;
}

.rental-card h3 {
  margin: 12px 0 8px;
  font-size: 14px;
}

.rental-card p {
  margin: 5px 0;
  color: #606266;
}

.flow-arrow {
  display: flex;
  align-items: center;
  justify-content: center;
  color: #409eff;
  font-size: 22px;
}

.feedback {
  margin-top: 14px;
}

.footer-hint {
  float: left;
  color: #6b7280;
  font-size: 12px;
  line-height: 32px;
}

@media (max-width: 700px) {
  .rental-flow {
    grid-template-columns: 1fr;
  }

  .flow-arrow {
    transform: rotate(90deg);
  }

  .footer-hint {
    display: block;
    float: none;
    margin-bottom: 8px;
  }
}
</style>
