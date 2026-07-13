<template>
  <van-popup
    :show="true"
    position="bottom"
    round
    :close-on-click-overlay="false"
    class="rental-confirmation-popup"
    data-testid="rental-confirmation-popup"
  >
    <div class="popup-content">
      <h2 class="popup-title">客户确认信息</h2>
      <pre class="confirmation-text" data-testid="rental-confirmation-text">{{ confirmation.text }}</pre>
      <div class="popup-actions">
        <van-button
          type="primary"
          block
          data-testid="copy-rental-confirmation"
          @click="copyAll"
        >
          复制全部
        </van-button>
        <van-button block data-testid="close-rental-confirmation" @click="emit('closed')">
          关闭
        </van-button>
      </div>
    </div>
  </van-popup>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { showFailToast, showSuccessToast } from 'vant'

import type { Rental } from '@/stores/gantt'
import { buildRentalConfirmation } from '@/utils/rentalConfirmation'

const props = defineProps<{ rental: Rental }>()
const emit = defineEmits<{ (event: 'closed'): void }>()

const confirmation = computed(() => buildRentalConfirmation(props.rental))

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
  if (copied) showSuccessToast('确认信息已复制')
  else showFailToast('自动复制失败，请手动选择文本复制')
}
</script>

<style scoped>
.rental-confirmation-popup {
  left: 3vw;
  width: 94vw;
  max-height: 82vh;
  overflow-y: auto;
}

.popup-content {
  padding: 20px 16px calc(16px + env(safe-area-inset-bottom));
}

.popup-title {
  margin: 0 0 16px;
  color: #323233;
  font-size: 18px;
  text-align: center;
}

.confirmation-text {
  margin: 0;
  padding: 14px;
  overflow-wrap: anywhere;
  white-space: pre-wrap;
  user-select: text;
  color: #323233;
  font-family: inherit;
  font-size: 14px;
  line-height: 1.7;
  background: #f7f8fa;
  border: 1px solid #ebedf0;
  border-radius: 8px;
}

.popup-actions {
  display: grid;
  gap: 10px;
  margin-top: 16px;
}
</style>
