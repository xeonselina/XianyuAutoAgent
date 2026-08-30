<template>
  <el-form-item label="租赁组合">
    <div class="combo-wrap">
      <el-radio-group v-model="combo">
        <el-radio-button
          v-for="opt in allowed"
          :key="opt.id"
          :label="opt.id"
        >
          {{ opt.name }}
        </el-radio-button>
      </el-radio-group>
      <div class="form-tip" v-if="!model">请先选择设备型号</div>
      <div class="form-tip" v-else>组合及发货物品由型号库维护，历史订单保存下单时的配置</div>
    </div>
  </el-form-item>
</template>

<script setup lang="ts">
import { computed, watch } from 'vue'
import {
  getDefaultRentalPackageId,
  getEnabledRentalPackages,
  isRentalPackageAllowed,
} from '@/config/rentalPackage'
import type { DeviceModel } from '@/stores/gantt'

const props = defineProps<{
  modelValue: string | undefined
  model: DeviceModel | null | undefined
  preserveUnknown?: boolean
  modelValueName?: string | null
}>()
const emit = defineEmits<{ (e: 'update:modelValue', v: string): void }>()

const allowed = computed(() => {
  const configured = getEnabledRentalPackages(props.model)
  if (
    props.preserveUnknown
    && props.modelValue
    && !configured.some((item) => item.id === props.modelValue)
  ) {
    return [{
      id: props.modelValue,
      name: `${props.modelValueName || '已停用组合'}（历史订单）`,
      is_active: false,
      items: [],
    }, ...configured]
  }
  return configured
})

const combo = computed<string>({
  get: () => (props.modelValue && (
    props.preserveUnknown || isRentalPackageAllowed(props.model, props.modelValue)
  ))
    ? props.modelValue
    : getDefaultRentalPackageId(props.model),
  set: (v) => emit('update:modelValue', v)
})

// 机型切换：当前组合不在新机型允许范围内 → 回退默认。
watch(() => props.model, (newModel) => {
  if (
    !props.preserveUnknown
    && props.modelValue
    && !isRentalPackageAllowed(newModel, props.modelValue)
  ) {
    emit('update:modelValue', getDefaultRentalPackageId(newModel))
  }
})
</script>

<style scoped>
.combo-wrap { display: flex; flex-direction: column; gap: 6px; }
.form-tip {
  font-size: 12px;
  color: var(--el-text-color-placeholder);
}
@media (max-width: 768px) {
  :deep(.el-radio-button__inner) { padding: 6px 10px; font-size: 12px; }
}
</style>
