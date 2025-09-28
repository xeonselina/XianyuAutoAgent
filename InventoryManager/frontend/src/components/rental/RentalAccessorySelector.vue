<template>
  <div class="rental-accessory-selector">
    <el-form-item label="附件选择" prop="accessories">
      <div class="device-selection">
        <el-select
          v-model="form.accessories"
          placeholder="选择附件(可多选)"
          clearable
          filterable
          multiple
          collapse-tags
          collapse-tags-tooltip
          style="flex: 1"
          :loading="loadingAccessories"
          loading-text="正在加载附件..."
          @change="handleAccessoryChange"
          @focus="handleAccessorySelectorFocus"
        >
          <el-option
            v-for="controller in availableControllers"
            :key="controller.id"
            :label="controller.name"
            :value="controller.id"
            :disabled="controller.isAvailable === false"
          >
            <div style="display: flex; justify-content: space-between; align-items: center; width: 100%">
              <span>{{ controller.name }}</span>
              <div style="display: flex; align-items: center; gap: 8px">
                <span style="color: var(--el-text-color-secondary); font-size: 13px">
                  {{ controller.model }}
                </span>
                <el-tag v-if="controller.isAvailable === false" type="danger" size="small" effect="dark">
                  档期不可用
                </el-tag>
                <el-tag v-else-if="controller.conflictReason" type="warning" size="small" effect="dark">
                  {{ controller.conflictReason }}
                </el-tag>
                <el-tag v-else type="success" size="small" effect="dark">
                  可用
                </el-tag>
              </div>
            </div>
          </el-option>
        </el-select>

        <el-button
          type="primary"
          size="small"
          @click="findAvailableAccessory"
          :loading="searchingAccessory"
          :disabled="!rental"
          style="margin-left: 8px;"
        >
          <el-icon><Search /></el-icon>
          查找手柄
        </el-button>
      </div>

      <!-- 当前选择的附件列表 -->
      <div v-if="currentControllers.length > 0" class="selected-accessories">
        <h4>已选择的附件:</h4>
        <div class="accessory-list">
          <div
            v-for="controller in currentControllers"
            :key="controller.id"
            class="accessory-item"
          >
            <div class="accessory-info">
              <strong>{{ controller.name }}</strong>
              <span class="accessory-model">{{ controller.model }}</span>
            </div>
            <el-button
              type="danger"
              size="small"
              @click="removeController(controller.id)"
              text
            >
              <el-icon><Delete /></el-icon>
              移除
            </el-button>
          </div>
        </div>
      </div>

      <div class="form-tip">手柄等附件与主设备共享档期，自动检查冲突</div>
    </el-form-item>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { Search, Delete } from '@element-plus/icons-vue'
import type { Rental } from '@/stores/gantt'

interface AccessoryWithStatus {
  id: number
  name: string
  model: string
  isAvailable?: boolean
  conflictReason?: string
}

interface Props {
  form: any
  rental: Rental
  availableControllers: AccessoryWithStatus[]
  loadingAccessories: boolean
  searchingAccessory: boolean
}

const props = defineProps<Props>()

const emit = defineEmits<{
  'find-accessory': []
  'remove-accessory': [id: number]
  'accessory-change': [accessoryIds: number[]]
  'accessory-selector-focus': []
}>()

const currentControllers = computed(() => {
  return props.availableControllers.filter(controller =>
    props.form.accessories.includes(controller.id)
  )
})

const findAvailableAccessory = () => {
  emit('find-accessory')
}

const removeController = (controllerId: number) => {
  emit('remove-accessory', controllerId)
}

const handleAccessoryChange = (accessoryIds: number[]) => {
  emit('accessory-change', accessoryIds)
}

const handleAccessorySelectorFocus = () => {
  emit('accessory-selector-focus')
}
</script>

<style scoped>
.device-selection {
  display: flex;
  align-items: center;
  width: 100%;
}

.selected-accessories {
  margin-top: 16px;
  padding: 12px;
  background: var(--el-bg-color-page);
  border-radius: 4px;
}

.selected-accessories h4 {
  margin: 0 0 8px 0;
  font-size: 14px;
  color: var(--el-text-color-primary);
}

.accessory-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.accessory-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 12px;
  background: white;
  border-radius: 4px;
  border: 1px solid var(--el-border-color-lighter);
}

.accessory-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.accessory-model {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.form-tip {
  font-size: 12px;
  color: var(--el-text-color-placeholder);
  margin-top: 4px;
}
</style>