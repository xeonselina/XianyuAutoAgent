<template>
  <el-dialog
    v-model="visible"
    title="客户确认信息"
    width="min(680px, 94vw)"
    :close-on-click-modal="false"
  >
    <pre class="confirmation-text" data-test="confirmation-text">{{ confirmation.text }}</pre>
    <template #footer>
      <el-button @click="visible = false">关闭</el-button>
      <el-button type="primary" data-test="copy-confirmation" @click="copyAll">
        复制全部
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { ElMessage } from 'element-plus'
import type { Rental } from '@/stores/gantt'
import { buildRentalConfirmation } from '@/utils/rentalConfirmation'

const props = defineProps<{ modelValue: boolean; rental: Rental | null }>()
const emit = defineEmits<{ (event: 'update:modelValue', value: boolean): void }>()

const visible = computed({
  get: () => props.modelValue,
  set: value => emit('update:modelValue', value),
})
const confirmation = computed(() => props.rental
  ? buildRentalConfirmation(props.rental)
  : { lines: [], text: '' })

const fallbackCopy = (text: string): boolean => {
  const textarea = document.createElement('textarea')
  textarea.value = text
  textarea.setAttribute('readonly', '')
  textarea.style.position = 'fixed'
  textarea.style.opacity = '0'
  document.body.appendChild(textarea)
  textarea.select()
  try {
    return document.execCommand('copy')
  } catch {
    return false
  } finally {
    textarea.remove()
  }
}

const copyAll = async () => {
  let copied = false
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(confirmation.value.text)
      copied = true
    }
  } catch {
    copied = false
  }
  if (!copied) copied = fallbackCopy(confirmation.value.text)
  if (copied) ElMessage.success('确认信息已复制')
  else ElMessage.error('自动复制失败，请手动选择文本复制')
}
</script>

<style scoped>
.confirmation-text {
  margin: 0;
  padding: 16px;
  overflow-wrap: anywhere;
  white-space: pre-wrap;
  user-select: text;
  color: #303133;
  line-height: 1.7;
  background: #f5f7fa;
  border: 1px solid #dcdfe6;
  border-radius: 6px;
}
</style>
