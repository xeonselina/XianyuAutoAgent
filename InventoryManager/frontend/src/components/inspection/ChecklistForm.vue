<template>
  <div class="checklist-form">
    <el-card shadow="never">
      <template #header>
        <div class="card-header">
          <span>验货清单</span>
          <el-tag :type="statusType">
            {{ statusText }}
          </el-tag>
        </div>
      </template>
      
      <div v-if="checkItems.length > 0" class="checklist-items">
        <div 
          v-for="(item, index) in checkItems" 
          :key="index"
          class="checklist-item"
          :class="{ 'checked': item.is_checked }"
          @click="handleToggle(index)"
        >
          <div class="item-content">
            <el-icon :size="24" class="check-icon">
              <component :is="item.is_checked ? 'CircleCheck' : 'CircleClose'" />
            </el-icon>
            <span class="item-name">{{ item.item_name }}</span>
          </div>
        </div>
      </div>
      
      <el-empty v-else description="暂无检查项" />
      
      <template #footer v-if="checkItems.length > 0">
        <div class="footer-actions">
          <el-button 
            type="primary" 
            size="large" 
            :loading="loading"
            @click="handleSubmit"
          >
            提交验货
          </el-button>
        </div>
      </template>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { CircleCheck, CircleClose } from '@element-plus/icons-vue'
import type { CheckItem } from '../../types/inspection'

// Props
interface Props {
  checkItems: CheckItem[]
  loading?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  loading: false
})

// Emits
const emit = defineEmits<{
  toggle: [index: number]
  submit: []
}>()

// 计算属性
const allChecked = computed(() => {
  return props.checkItems.length > 0 && props.checkItems.every(item => item.is_checked)
})

const statusText = computed(() => {
  if (props.checkItems.length === 0) return '无检查项'
  return allChecked.value ? '验机正常' : '验机异常'
})

const statusType = computed(() => {
  if (props.checkItems.length === 0) return 'info'
  return allChecked.value ? 'success' : 'warning'
})

// 方法
const handleToggle = (index: number) => {
  emit('toggle', index)
}

const handleSubmit = () => {
  emit('submit')
}
</script>

<style scoped>
.checklist-form {
  margin-bottom: 20px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-weight: bold;
}

.checklist-items {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.checklist-item {
  display: flex;
  align-items: center;
  padding: 16px;
  border: 2px solid #dcdfe6;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.3s;
  background-color: #fff;
}

.checklist-item:hover {
  border-color: #409eff;
  background-color: #f5f7fa;
}

.checklist-item.checked {
  border-color: #67c23a;
  background-color: #f0f9ff;
}

.item-content {
  display: flex;
  align-items: center;
  width: 100%;
}

.check-icon {
  margin-right: 12px;
  flex-shrink: 0;
}

.checklist-item:not(.checked) .check-icon {
  color: #909399;
}

.checklist-item.checked .check-icon {
  color: #67c23a;
}

.item-name {
  font-size: 16px;
  font-weight: 500;
}

.footer-actions {
  display: flex;
  justify-content: center;
  padding-top: 16px;
}

.footer-actions .el-button {
  width: 100%;
  max-width: 400px;
}

/* iPad 优化 */
@media (min-width: 768px) {
  .checklist-item {
    padding: 20px;
  }
  
  .item-name {
    font-size: 18px;
  }
  
  .check-icon {
    font-size: 28px;
  }
}
</style>
