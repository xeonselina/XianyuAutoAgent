<template>
  <el-dialog
    v-model="dialogVisible"
    title="编辑验货记录"
    width="90%"
    :style="{ maxWidth: '600px' }"
    @close="handleClose"
  >
    <div class="dialog-content">
      <!-- 设备和客户信息 -->
      <el-descriptions :column="1" border class="info-section">
        <el-descriptions-item label="设备">
          {{ record?.device?.name || '-' }}
        </el-descriptions-item>
        <el-descriptions-item label="客户">
          {{ record?.rental?.customer_name || '-' }}
        </el-descriptions-item>
        <el-descriptions-item label="电话">
          {{ record?.rental?.customer_phone || '-' }}
        </el-descriptions-item>
      </el-descriptions>
      
      <!-- 检查清单 -->
      <div class="checklist-section">
        <h3>检查清单</h3>
        <el-checkbox-group v-model="checkedItems">
          <div
            v-for="(item, index) in checkItems"
            :key="item.id"
            class="check-item"
          >
            <el-checkbox
              :label="item.id"
              :disabled="loading"
            >
              {{ item.item_name }}
            </el-checkbox>
          </div>
        </el-checkbox-group>
      </div>
      
      <!-- 状态预览 -->
      <div class="status-preview">
        <span class="label">验货状态:</span>
        <el-tag :type="previewStatusType" size="large">
          {{ previewStatusText }}
        </el-tag>
      </div>
    </div>
    
    <template #footer>
      <el-button @click="handleClose" :disabled="loading">取消</el-button>
      <el-button type="primary" @click="handleSubmit" :loading="loading">
        保存
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useInspectionStore } from '../../stores/inspection'
import type { InspectionRecord, CheckItem } from '../../types/inspection'
import { ElMessage } from 'element-plus'

interface Props {
  visible: boolean
  record: InspectionRecord | null
}

const props = defineProps<Props>()

const emit = defineEmits<{
  'update:visible': [value: boolean]
  'success': []
}>()

// Store
const inspectionStore = useInspectionStore()

// 状态
const dialogVisible = computed({
  get: () => props.visible,
  set: (value) => emit('update:visible', value)
})

const loading = ref(false)
const checkItems = ref<CheckItem[]>([])
const checkedItems = ref<number[]>([])

// 计算属性
const previewStatusType = computed(() => {
  const allChecked = checkItems.value.every((item) =>
    checkedItems.value.includes(item.id!)
  )
  return allChecked ? 'success' : 'warning'
})

const previewStatusText = computed(() => {
  const allChecked = checkItems.value.every((item) =>
    checkedItems.value.includes(item.id!)
  )
  return allChecked ? '验机正常' : '验机异常'
})

// 监听 record 变化,初始化表单
watch(
  () => props.record,
  (newRecord) => {
    if (newRecord) {
      checkItems.value = newRecord.check_items || []
      checkedItems.value = checkItems.value
        .filter((item) => item.is_checked)
        .map((item) => item.id!)
    }
  },
  { immediate: true }
)

// 方法
const handleClose = () => {
  dialogVisible.value = false
}

const handleSubmit = async () => {
  if (!props.record) return
  
  loading.value = true
  try {
    // 先加载记录到store
    await inspectionStore.fetchInspectionById(props.record.id)
    
    // 更新store的checkItems状态
    inspectionStore.checkItems.forEach((item, index) => {
      if (item.id) {
        inspectionStore.checkItems[index].is_checked = checkedItems.value.includes(item.id)
      }
    })
    
    // 调用store方法更新
    const success = await inspectionStore.updateInspectionRecord(props.record.id)
    
    if (success) {
      emit('success')
      handleClose()
    }
  } catch (error) {
    ElMessage.error('更新验货记录失败')
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.dialog-content {
  padding: 0 4px;
}

.info-section {
  margin-bottom: 20px;
}

.checklist-section {
  margin-bottom: 20px;
}

.checklist-section h3 {
  font-size: 16px;
  font-weight: bold;
  margin-bottom: 12px;
  color: #303133;
}

.check-item {
  padding: 12px 0;
  border-bottom: 1px solid #ebeef5;
}

.check-item:last-child {
  border-bottom: none;
}

.status-preview {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px;
  background-color: #f5f7fa;
  border-radius: 4px;
}

.status-preview .label {
  font-weight: bold;
  color: #606266;
}

/* iPad 优化 */
@media (min-width: 768px) {
  .checklist-section h3 {
    font-size: 18px;
  }
  
  :deep(.el-checkbox__label) {
    font-size: 16px;
  }
}
</style>
