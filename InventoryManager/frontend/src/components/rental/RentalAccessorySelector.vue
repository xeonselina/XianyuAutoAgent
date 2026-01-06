<template>
  <div class="rental-accessory-selector">
    <!-- 配套附件 - 复选框 -->
    <el-form-item label="配套附件">
      <el-checkbox-group v-model="form.bundledAccessories" @change="handleBundledAccessoriesChange">
        <el-checkbox label="handle">手柄</el-checkbox>
        <el-checkbox label="lens_mount">镜头支架</el-checkbox>
      </el-checkbox-group>
      <div class="form-tip">手柄和镜头支架已与设备配齐，无需选择具体编号</div>
    </el-form-item>

    <!-- 代传照片 - 复选框 -->
    <el-form-item label="附加服务">
      <el-checkbox v-model="form.photoTransfer">代传照片</el-checkbox>
      <div class="form-tip">勾选此项表示需要代替客户传输照片</div>
    </el-form-item>

    <!-- 库存附件 - 手机支架 -->
    <el-form-item label="手机支架">
      <div class="device-selection">
        <el-select 
          v-model="form.phoneHolderId" 
          placeholder="选择手机支架(可选)" 
          clearable
          filterable
          :loading="loadingAccessories"
          @change="handleInventoryAccessoryChange"
          @focus="handleAccessorySelectorFocus"
        >
          <el-option
            v-for="holder in phoneHolders"
            :key="holder.id"
            :label="holder.name"
            :value="holder.id"
            :disabled="holder.isAvailable === false"
          >
            <div style="display: flex; justify-content: space-between; align-items: center; width: 100%">
              <span>{{ holder.name }}</span>
              <div style="display: flex; align-items: center; gap: 8px">
                <span style="color: var(--el-text-color-secondary); font-size: 13px">
                  {{ holder.model }}
                </span>
                <el-tag v-if="holder.isAvailable === false" type="danger" size="small" effect="dark">
                  档期不可用
                </el-tag>
                <el-tag v-else-if="holder.conflictReason" type="warning" size="small" effect="dark">
                  {{ holder.conflictReason }}
                </el-tag>
                <el-tag v-else type="success" size="small" effect="dark">
                  可用
                </el-tag>
              </div>
            </div>
          </el-option>
        </el-select>
      </div>
      <div class="form-tip">手机支架为库存附件，需选择具体编号</div>
    </el-form-item>

    <!-- 库存附件 - 三脚架 -->
    <el-form-item label="三脚架">
      <div class="device-selection">
        <el-select 
          v-model="form.tripodId" 
          placeholder="选择三脚架(可选)" 
          clearable
          filterable
          :loading="loadingAccessories"
          @change="handleInventoryAccessoryChange"
          @focus="handleAccessorySelectorFocus"
        >
          <el-option
            v-for="tripod in tripods"
            :key="tripod.id"
            :label="tripod.name"
            :value="tripod.id"
            :disabled="tripod.isAvailable === false"
          >
            <div style="display: flex; justify-content: space-between; align-items: center; width: 100%">
              <span>{{ tripod.name }}</span>
              <div style="display: flex; align-items: center; gap: 8px">
                <span style="color: var(--el-text-color-secondary); font-size: 13px">
                  {{ tripod.model }}
                </span>
                <el-tag v-if="tripod.isAvailable === false" type="danger" size="small" effect="dark">
                  档期不可用
                </el-tag>
                <el-tag v-else-if="tripod.conflictReason" type="warning" size="small" effect="dark">
                  {{ tripod.conflictReason }}
                </el-tag>
                <el-tag v-else type="success" size="small" effect="dark">
                  可用
                </el-tag>
              </div>
            </div>
          </el-option>
        </el-select>
      </div>
      <div class="form-tip">三脚架为库存附件，需选择具体编号</div>
    </el-form-item>

    <!-- 已选择的附件汇总 -->
    <div v-if="hasSelectedAccessories" class="selected-accessories">
      <h4>已选择的附件:</h4>
      <div class="accessory-list">
        <!-- 配套附件 -->
        <div v-if="form.bundledAccessories.includes('handle')" class="accessory-item bundled">
          <div class="accessory-info">
            <strong>手柄</strong>
            <span class="accessory-model">(配套附件)</span>
          </div>
          <el-tag type="success" size="small">配套</el-tag>
        </div>
        <div v-if="form.bundledAccessories.includes('lens_mount')" class="accessory-item bundled">
          <div class="accessory-info">
            <strong>镜头支架</strong>
            <span class="accessory-model">(配套附件)</span>
          </div>
          <el-tag type="success" size="small">配套</el-tag>
        </div>
        
        <!-- 库存附件 -->
        <div v-if="selectedPhoneHolder" class="accessory-item inventory">
          <div class="accessory-info">
            <strong>{{ selectedPhoneHolder.name }}</strong>
            <span class="accessory-model">{{ selectedPhoneHolder.model }}</span>
          </div>
          <div style="display: flex; gap: 8px; align-items: center">
            <el-tag type="info" size="small">库存</el-tag>
            <el-button
              type="danger"
              size="small"
              @click="form.phoneHolderId = null; handleInventoryAccessoryChange()"
              text
            >
              <el-icon><Delete /></el-icon>
              移除
            </el-button>
          </div>
        </div>
        <div v-if="selectedTripod" class="accessory-item inventory">
          <div class="accessory-info">
            <strong>{{ selectedTripod.name }}</strong>
            <span class="accessory-model">{{ selectedTripod.model }}</span>
          </div>
          <div style="display: flex; gap: 8px; align-items: center">
            <el-tag type="info" size="small">库存</el-tag>
            <el-button
              type="danger"
              size="small"
              @click="form.tripodId = null; handleInventoryAccessoryChange()"
              text
            >
              <el-icon><Delete /></el-icon>
              移除
            </el-button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { Delete } from '@element-plus/icons-vue'
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

// 过滤手机支架
const phoneHolders = computed(() => {
  return props.availableControllers.filter(a => 
    a.name.includes('手机支架') || a.name.toLowerCase().includes('phone')
  )
})

// 过滤三脚架
const tripods = computed(() => {
  return props.availableControllers.filter(a => 
    a.name.includes('三脚架') || a.name.toLowerCase().includes('tripod')
  )
})

// 选中的手机支架
const selectedPhoneHolder = computed(() => {
  if (!props.form.phoneHolderId) return null
  return props.availableControllers.find(a => a.id === props.form.phoneHolderId)
})

// 选中的三脚架
const selectedTripod = computed(() => {
  if (!props.form.tripodId) return null
  return props.availableControllers.find(a => a.id === props.form.tripodId)
})

// 是否有选中的附件
const hasSelectedAccessories = computed(() => {
  return props.form.bundledAccessories.length > 0 || 
         props.form.phoneHolderId !== null || 
         props.form.tripodId !== null
})

const handleBundledAccessoriesChange = () => {
  // 通知父组件配套附件改变（保持accessories数组为空，只用新字段）
  const accessoryIds = [props.form.phoneHolderId, props.form.tripodId]
    .filter((id): id is number => id !== null)
  emit('accessory-change', accessoryIds)
}

const handleInventoryAccessoryChange = () => {
  // 通知父组件库存附件改变
  const accessoryIds = [props.form.phoneHolderId, props.form.tripodId]
    .filter((id): id is number => id !== null)
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

.accessory-item.bundled {
  border-left: 3px solid var(--el-color-success);
}

.accessory-item.inventory {
  border-left: 3px solid var(--el-color-info);
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
