<script setup lang="ts">
import axios, { isAxiosError } from 'axios'
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'

import { useTenantStore } from '@/stores/tenant'


type ImpactRow = { rental_id: number; reason?: string }
type MovementPreview = {
  token: string
  auto_fixable: ImpactRow[]
  shortages: ImpactRow[]
  manual: ImpactRow[]
  blocked: ImpactRow[]
}

const props = defineProps<{
  modelValue: boolean
  deviceId: number
  currentWarehouseId: number
}>()
const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  moved: []
}>()

const tenant = useTenantStore()
const targetWarehouseId = ref<number | null>(null)
const preview = ref<MovementPreview | null>(null)
const loading = ref(false)

const candidateWarehouses = computed(() => tenant.warehouses.filter(
  (warehouse) => warehouse.id !== props.currentWarehouseId,
))

const reset = () => {
  preview.value = null
  targetWarehouseId.value = candidateWarehouses.value[0]?.id ?? null
}

const requestPreview = async () => {
  if (targetWarehouseId.value === null) throw new Error('请选择目标仓库')
  const response = await axios.post(
    `/api/devices/${props.deviceId}/movement-preview`,
    { target_warehouse_id: targetWarehouseId.value },
  )
  if (!response.data.success || !response.data.data) {
    throw new Error(response.data.message || '移仓预览失败')
  }
  const result = response.data.data as MovementPreview
  preview.value = result
  return result
}

const handlePreview = async () => {
  loading.value = true
  try {
    await requestPreview()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '移仓预览失败')
  } finally {
    loading.value = false
  }
}

const executeToken = async (token: string) => axios.post(
  `/api/devices/${props.deviceId}/move`,
  { token },
)

const handleConfirm = async () => {
  if (!preview.value) return
  loading.value = true
  try {
    try {
      await executeToken(preview.value.token)
    } catch (error) {
      if (!isAxiosError(error) || error.response?.status !== 409) throw error
      const refreshed = await requestPreview()
      await executeToken(refreshed.token)
    }
    ElMessage.success('设备移仓完成')
    emit('moved')
    emit('update:modelValue', false)
  } catch (error) {
    const message = isAxiosError<{ message?: string }>(error)
      ? error.response?.data?.message
      : undefined
    ElMessage.error(message || (error instanceof Error ? error.message : '设备移仓失败'))
  } finally {
    loading.value = false
  }
}

watch(
  () => [props.modelValue, props.deviceId, props.currentWarehouseId],
  ([visible]) => {
    if (visible) reset()
  },
  { immediate: true },
)
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    title="设备移仓"
    width="620px"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <el-select
      :model-value="targetWarehouseId"
      data-testid="movement-target"
      placeholder="选择目标仓库"
      style="width: 100%"
      @update:model-value="targetWarehouseId = $event; preview = null"
    >
      <el-option
        v-for="warehouse in candidateWarehouses"
        :key="warehouse.id"
        :label="warehouse.name"
        :value="warehouse.id"
      />
    </el-select>

    <div v-if="preview" class="impact-list">
      <el-alert type="success" :closable="false">
        可自动修正：{{ preview.auto_fixable.length }} 条
      </el-alert>
      <el-alert type="warning" :closable="false">
        缺货：{{ preview.shortages.length }} 条
      </el-alert>
      <el-alert type="warning" :closable="false">
        人工处理：{{ preview.manual.length }} 条
      </el-alert>
      <el-alert type="error" :closable="false">
        已阻止：{{ preview.blocked.length }} 条
      </el-alert>
    </div>

    <template #footer>
      <el-button @click="emit('update:modelValue', false)">取消</el-button>
      <el-button
        data-testid="preview-movement"
        :loading="loading"
        @click="handlePreview"
      >
        预览影响
      </el-button>
      <el-button
        v-if="preview"
        data-testid="confirm-movement"
        type="primary"
        :loading="loading"
        @click="handleConfirm"
      >
        确认移仓
      </el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.impact-list { display: grid; gap: 8px; margin-top: 16px; }
</style>
