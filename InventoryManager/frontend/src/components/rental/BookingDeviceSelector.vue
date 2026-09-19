<template>
  <div class="device-selection">
    <el-select
      :model-value="modelValue"
      @update:model-value="emit('update:modelValue', $event)"
      placeholder="请选择设备"
      style="flex: 1"
      clearable
      filterable
      @focus="emit('focus')"
    >
      <el-option
        v-for="device in devices"
        :key="device.id"
        :label="device.name"
        :value="device.id"
        :disabled="lifecycleLabel(device) !== null || excludedIds.includes(device.id)"
      >
        <div class="device-option">
          <span>{{ device.name }}</span>
          <div class="device-status">
            <span class="device-model">{{ device.model }}</span>
            <el-tag
              v-if="lifecycleLabel(device)"
              type="info"
              size="small"
              effect="dark"
            >
              {{ lifecycleLabel(device) }}
            </el-tag>
            <el-tag
              v-else-if="checked && isAvailable(device.id)"
              type="success"
              size="small"
              effect="dark"
            >
              可用
            </el-tag>
            <el-tag
              v-else-if="checked"
              type="danger"
              size="small"
              effect="dark"
            >
              档期不可用
            </el-tag>
          </div>
        </div>
      </el-option>
    </el-select>
    <el-button
      type="info"
      @click="emit('search')"
      :loading="loading"
      :disabled="!canSearch"
    >
      查找档期
    </el-button>
  </div>
  <div class="form-tip">选择具体设备或点击查找档期自动匹配可用设备</div>
</template>
<script setup lang="ts">
import type { Device } from '@/stores/gantt'
defineProps<{
  modelValue: number | null
  devices: Device[]
  excludedIds: number[]
  checked: boolean
  isAvailable: (id: number) => boolean
  lifecycleLabel: (device: Device) => string | null
  loading: boolean
  canSearch: boolean
}>()
const emit = defineEmits<{
  'update:modelValue': [value: number | null]
  focus: []
  search: []
}>()
</script>
<style scoped>
.device-selection { display: flex; width: 100%; gap: 8px; }
.device-option, .device-status { display: flex; align-items: center; gap: 8px; }
.device-option { justify-content: space-between; }
.device-model, .form-tip { color: #909399; font-size: 12px; }
.form-tip { margin-top: 4px; }
</style>
