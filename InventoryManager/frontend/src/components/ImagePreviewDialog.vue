<template>
  <el-dialog
    v-model="dialogVisible"
    title="身份证预览"
    width="80%"
    :close-on-click-modal="true"
    :close-on-press-escape="true"
    @close="handleClose"
    class="image-preview-dialog"
  >
    <div class="image-container">
      <img 
        :src="imageUrl" 
        :alt="imageAlt" 
        class="preview-image"
        @load="handleImageLoad"
        @error="handleImageError"
      />
    </div>
    
    <template #footer>
      <div class="dialog-footer">
        <el-button @click="handleClose">关闭</el-button>
        <el-button 
          type="primary" 
          @click="downloadImage"
          :disabled="!imageUrl"
        >
          下载图片
        </el-button>
      </div>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'

const props = defineProps<{
  modelValue: boolean
  imageUrl: string
  imageAlt?: string
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
}>()

const imageLoaded = ref(false)
const imageError = ref(false)

const dialogVisible = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value)
})

const handleImageLoad = () => {
  imageLoaded.value = true
  imageError.value = false
}

const handleImageError = () => {
  imageError.value = true
  imageLoaded.value = false
  ElMessage.error('图片加载失败')
}

const handleClose = () => {
  emit('update:modelValue', false)
}

const downloadImage = () => {
  if (!props.imageUrl) return
  
  try {
    const link = document.createElement('a')
    link.href = props.imageUrl
    link.download = `身份证_${new Date().getTime()}.jpg`
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    ElMessage.success('图片下载成功')
  } catch (error) {
    ElMessage.error('图片下载失败')
  }
}
</script>

<style scoped>
.image-preview-dialog {
  max-width: 90vw;
}

.image-container {
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 400px;
  background-color: #f5f5f5;
  border-radius: 8px;
  overflow: hidden;
}

.preview-image {
  max-width: 100%;
  max-height: 70vh;
  object-fit: contain;
  border-radius: 4px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
  cursor: pointer;
  transition: transform 0.2s ease;
}

.preview-image:hover {
  transform: scale(1.02);
}

.dialog-footer {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
}

/* 响应式设计 */
@media (max-width: 768px) {
  .image-preview-dialog {
    width: 95% !important;
  }
  
  .image-container {
    min-height: 300px;
  }
  
  .preview-image {
    max-height: 60vh;
  }
}
</style>
