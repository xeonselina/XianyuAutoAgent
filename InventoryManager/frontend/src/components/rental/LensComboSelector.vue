<template>
  <el-form-item label="镜头组合">
    <div class="combo-wrap">
      <el-radio-group v-model="combo">
        <el-radio-button
          v-for="opt in allowed"
          :key="opt"
          :label="opt"
        >
          {{ display(opt) }}
        </el-radio-button>
      </el-radio-group>
      <div class="form-tip" v-if="!modelName">未识别机型，使用默认组合</div>
      <div class="form-tip" v-else>不同组合会影响发货单/面单的品名清单</div>
    </div>
  </el-form-item>
</template>

<script setup lang="ts">
import { computed, watch } from 'vue'
import {
  getAllowedCombos,
  getDefaultCombo,
  isComboAllowed,
  lensComboDisplay,
  type LensCombo,
} from '@/config/lensCombo'

const props = defineProps<{
  modelValue: LensCombo | undefined
  modelName: string | null | undefined
}>()
const emit = defineEmits<{ (e: 'update:modelValue', v: LensCombo): void }>()

const allowed = computed(() => getAllowedCombos(props.modelName ?? undefined))

const combo = computed<LensCombo>({
  get: () => (props.modelValue && isComboAllowed(props.modelName ?? undefined, props.modelValue))
    ? props.modelValue
    : getDefaultCombo(props.modelName ?? undefined),
  set: (v) => emit('update:modelValue', v)
})

const display = (v: LensCombo) => lensComboDisplay(v)

// 机型切换：当前 combo 不在新机型允许范围内 → 回退默认
watch(() => props.modelName, (newModel) => {
  if (props.modelValue && !isComboAllowed(newModel ?? undefined, props.modelValue)) {
    emit('update:modelValue', getDefaultCombo(newModel ?? undefined))
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
