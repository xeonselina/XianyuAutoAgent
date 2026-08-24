<template>
  <div class="inspection-view">
    <div class="container">
      <h1 class="page-title">{{ isEditMode ? '编辑验货记录' : '设备验货' }}</h1>
      
      <!-- 设备搜索 - 仅在非编辑模式显示 -->
      <DeviceSearchInput 
        v-if="!isEditMode"
        ref="deviceSearchRef"
        :loading="inspectionStore.loading"
        @search="handleSearch"
      />
      
      <!-- 租赁信息 -->
      <RentalInfoCard 
        v-if="inspectionStore.currentRental"
        :rental="inspectionStore.currentRental"
      />

      <el-card
        v-if="inspectionStore.currentRental && !isEditMode"
        class="receipt-card"
      >
        <template #header>收货仓库与实际附件</template>
        <el-form label-width="110px">
          <el-form-item label="收货仓库">
            <el-select v-model="inspectionStore.receivingWarehouseId">
              <el-option
                v-for="warehouse in tenantStore.warehouses"
                :key="warehouse.id"
                :label="warehouse.name"
                :value="warehouse.id"
              />
            </el-select>
          </el-form-item>
          <el-form-item
            v-if="inspectionStore.currentRental.accessories?.length"
            label="实际收到"
          >
            <el-checkbox-group v-model="inspectionStore.receivedDeviceIds">
              <el-checkbox
                v-for="accessory in inspectionStore.currentRental.accessories"
                :key="accessory.id"
                :value="accessory.id"
              >
                {{ accessory.name }}
              </el-checkbox>
            </el-checkbox-group>
          </el-form-item>
        </el-form>
      </el-card>
      
      <!-- 验货清单 -->
      <ChecklistForm 
        v-if="inspectionStore.checkItems.length > 0"
        :check-items="inspectionStore.checkItems"
        :loading="inspectionStore.loading"
        :submit-text="isEditMode ? '保存修改' : '确认验机'"
        @toggle="handleToggleCheckItem"
        @submit="handleSubmit"
      />
      
      <!-- 验货成功提示 -->
      <el-result
        v-if="showSuccessResult"
        icon="success"
        :title="successTitle"
        :sub-title="successSubTitle"
      >
        <template #extra>
          <el-button type="primary" size="large" @click="handleReset">
            {{ isEditMode ? '返回列表' : '继续验货' }}
          </el-button>
        </template>
      </el-result>

      <el-card v-if="inspectionStore.warehouseImpacts" class="impact-card">
        <template #header>入仓影响</template>
        <p>
          可自动修正 {{ inspectionStore.warehouseImpacts.auto_fixable.length }} 条，
          缺货 {{ inspectionStore.warehouseImpacts.shortages.length }} 条，
          人工处理 {{ inspectionStore.warehouseImpacts.manual.length }} 条，
          已阻止 {{ inspectionStore.warehouseImpacts.blocked.length }} 条。
        </p>
        <el-button
          type="primary"
          :loading="inspectionStore.loading"
          @click="handleRepairImpacts"
        >
          一键修正可处理租赁
        </el-button>
      </el-card>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useInspectionStore } from '../stores/inspection'
import DeviceSearchInput from '../components/inspection/DeviceSearchInput.vue'
import RentalInfoCard from '../components/inspection/RentalInfoCard.vue'
import ChecklistForm from '../components/inspection/ChecklistForm.vue'
import { useTenantStore } from '@/stores/tenant'

// Route & Router
const route = useRoute()
const router = useRouter()

// Store
const inspectionStore = useInspectionStore()
const tenantStore = useTenantStore()

// Refs
const deviceSearchRef = ref<InstanceType<typeof DeviceSearchInput>>()

// 状态
const showSuccessResult = ref(false)
const isEditMode = ref(false)
const editingRecordId = ref<number | null>(null)

// 计算属性
const successTitle = computed(() => {
  if (!inspectionStore.currentInspection) return '验货完成'
  return inspectionStore.currentInspection.status === 'normal' ? '验机正常' : '验机异常'
})

const successSubTitle = computed(() => {
  if (!inspectionStore.currentInspection) return ''
  if (inspectionStore.currentInspection.status === 'normal') {
    return '所有检查项均正常，设备状态良好'
  } else {
    return '存在异常检查项，请注意检查'
  }
})

// 方法
const handleSearch = async (deviceName: string) => {
  showSuccessResult.value = false
  const success = await inspectionStore.fetchLatestRentalByDeviceName(deviceName)
  
  if (!success) {
    // 错误已在 store 中处理并显示
    inspectionStore.reset()
  }
}

const handleToggleCheckItem = (index: number) => {
  inspectionStore.toggleCheckItem(index)
}

const handleSubmit = async () => {
  let success = false
  
  if (isEditMode.value && editingRecordId.value) {
    // 编辑模式: 更新验货记录
    success = await inspectionStore.updateInspectionRecord(editingRecordId.value)
    if (success) {
      showSuccessResult.value = true
    }
  } else {
    // 创建模式: 创建新的验货记录
    success = await inspectionStore.submitInspection()
    if (success) {
      if (inspectionStore.warehouseImpacts) {
        showSuccessResult.value = true
      } else {
        inspectionStore.reset()
        setTimeout(() => {
          deviceSearchRef.value?.clearAndFocus()
        }, 100)
      }
    }
  }
}

const handleRepairImpacts = async () => {
  await inspectionStore.repairWarehouseImpacts()
}

const handleReset = () => {
  showSuccessResult.value = false
  inspectionStore.reset()
  
  if (isEditMode.value) {
    // 编辑模式下返回验货记录列表
    router.push('/inspection-records')
  } else {
    // 创建模式下重置状态继续验货
    isEditMode.value = false
    editingRecordId.value = null
    
    // 清空设备名称并聚焦输入框
    setTimeout(() => {
      deviceSearchRef.value?.clearAndFocus()
    }, 100)
  }
}

// 生命周期 - 检查是否是编辑模式
onMounted(async () => {
  await tenantStore.loadWarehouses()
  const editId = route.query.edit
  if (editId) {
    isEditMode.value = true
    editingRecordId.value = Number(editId)
    
    // 加载验货记录
    const success = await inspectionStore.fetchInspectionById(editingRecordId.value)
    if (success && inspectionStore.currentInspection) {
      // 加载关联的租赁记录信息用于显示
      inspectionStore.currentRental = inspectionStore.currentInspection.rental || null
    }
  }
})
</script>

<style scoped>
.inspection-view {
  min-height: 100vh;
  background-color: #f5f7fa;
  padding: 20px;
}

.container {
  max-width: 800px;
  margin: 0 auto;
}

.page-title {
  font-size: 28px;
  font-weight: bold;
  margin-bottom: 24px;
  text-align: center;
  color: #303133;
}

.receipt-card, .impact-card { margin-bottom: 20px; }

/* iPad 优化 */
@media (min-width: 768px) {
  .inspection-view {
    padding: 40px 20px;
  }
  
  .page-title {
    font-size: 32px;
    margin-bottom: 32px;
  }
  
  .container {
    max-width: 900px;
  }
}

/* 移动端优化 */
@media (max-width: 767px) {
  .inspection-view {
    padding: 16px;
  }
  
  .page-title {
    font-size: 24px;
    margin-bottom: 20px;
  }
}
</style>
