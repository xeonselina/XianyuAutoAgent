<template>
  <div class="device-search-input">
    <el-card shadow="never">
      <template #header>
        <div class="card-header">
          <span>设备查询</span>
        </div>
      </template>
      <el-form @submit.prevent="handleSearch">
        <el-form-item label="设备名称" label-width="80px">
          <el-input
            ref="inputRef"
            v-model="deviceName"
            type="text"
            inputmode="numeric"
            pattern="[0-9]*"
            placeholder="请输入设备名称（纯数字）"
            clearable
            size="large"
            @keyup.enter="handleSearch"
          >
            <template #append>
              <el-button type="primary" :loading="loading" @click="handleSearch">
                查询
              </el-button>
            </template>
          </el-input>
        </el-form-item>
      </el-form>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { ElMessage } from 'element-plus'

// Props
interface Props {
  loading?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  loading: false
})

// Emits
const emit = defineEmits<{
  search: [deviceName: string]
}>()

// 状态
const deviceName = ref('')
const inputRef = ref()

// 方法
const handleSearch = () => {
  const name = deviceName.value.trim()
  
  if (!name) {
    ElMessage.warning('请输入设备名称')
    return
  }
  
  // 验证设备名称是否为纯数字
  if (!/^\d+$/.test(name)) {
    ElMessage.warning('设备名称必须为纯数字')
    return
  }
  
  emit('search', name)
}

// 清空并聚焦输入框
const clearAndFocus = () => {
  deviceName.value = ''
  // 使用 nextTick 确保 DOM 更新后再聚焦
  setTimeout(() => {
    inputRef.value?.focus()
  }, 100)
}

// 暴露方法给父组件
defineExpose({
  clearAndFocus
})
</script>

<style scoped>
.device-search-input {
  margin-bottom: 20px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-weight: bold;
}

/* iPad 优化 */
@media (min-width: 768px) {
  :deep(.el-input__inner) {
    font-size: 18px;
    height: 48px;
  }
  
  :deep(.el-button) {
    font-size: 16px;
    padding: 12px 20px;
  }
}
</style>
