<template>
  <div class="inspection-records-view">
    <div class="container">
      <div class="header-section">
        <h1 class="page-title">验货记录</h1>
        <el-button type="primary" size="large" @click="handleStartInspection" class="start-btn">
          <el-icon><Plus /></el-icon>
          开始验机
        </el-button>
      </div>
      
      <!-- 筛选器 -->
      <el-card shadow="never" class="filter-card">
        <el-form :inline="true" :model="filterForm" class="filter-form">
          <el-form-item label="设备名称">
            <el-input
              v-model="filterForm.device_name"
              placeholder="输入设备名称"
              clearable
              @clear="handleSearch"
              @keyup.enter="handleSearch"
            />
          </el-form-item>
          
          <el-form-item label="验货状态">
            <el-select
              v-model="filterForm.status"
              placeholder="全部状态"
              clearable
              @change="handleSearch"
            >
              <el-option label="验机正常" value="normal" />
              <el-option label="验机异常" value="abnormal" />
            </el-select>
          </el-form-item>
          
          <el-form-item>
            <el-button type="primary" @click="handleSearch" :loading="inspectionStore.loading">
              搜索
            </el-button>
            <el-button @click="handleClear">重置</el-button>
          </el-form-item>
        </el-form>
      </el-card>
      
      <!-- 记录列表 -->
      <div v-loading="inspectionStore.loading" class="records-list">
        <InspectionRecordCard
          v-for="record in inspectionStore.inspectionRecords"
          :key="record.id"
          :record="record"
          @view="handleView"
          @edit="handleEdit"
        />
        
        <el-empty
          v-if="!inspectionStore.loading && inspectionStore.inspectionRecords.length === 0"
          description="暂无验货记录"
        />
      </div>
      
      <!-- 分页 -->
      <el-pagination
        v-if="inspectionStore.pagination.total > 0"
        v-model:current-page="currentPage"
        v-model:page-size="pageSize"
        :page-sizes="[10, 20, 50, 100]"
        :total="inspectionStore.pagination.total"
        layout="total, sizes, prev, pager, next, jumper"
        class="pagination"
        @size-change="handleSizeChange"
        @current-change="handlePageChange"
      />
    </div>
    
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useInspectionStore } from '../stores/inspection'
import InspectionRecordCard from '../components/inspection/InspectionRecordCard.vue'
import type { InspectionRecord } from '../types/inspection'
import { ElMessage } from 'element-plus'
import { Plus } from '@element-plus/icons-vue'

// Router
const router = useRouter()

// Store
const inspectionStore = useInspectionStore()

// 状态
const filterForm = ref({
  device_name: '',
  status: undefined as 'normal' | 'abnormal' | undefined
})

const currentPage = ref(1)
const pageSize = ref(20)

// 方法
const fetchRecords = async () => {
  await inspectionStore.fetchInspectionRecords({
    device_name: filterForm.value.device_name,
    status: filterForm.value.status,
    page: currentPage.value,
    per_page: pageSize.value
  })
}

const handleSearch = () => {
  currentPage.value = 1
  fetchRecords()
}

const handleStartInspection = () => {
  window.open('/inspection', '_blank')
}

const handleClear = async () => {
  filterForm.value = {
    device_name: '',
    status: undefined
  }
  currentPage.value = 1
  await fetchRecords()
}

const handlePageChange = (page: number) => {
  currentPage.value = page
  fetchRecords()
}

const handleSizeChange = (size: number) => {
  pageSize.value = size
  currentPage.value = 1
  fetchRecords()
}

const handleView = (record: InspectionRecord) => {
  // 可以跳转到详情页或者打开详情对话框
  ElMessage.info('查看详情功能待实现')
}

const handleEdit = (record: InspectionRecord) => {
  // 跳转到验货页面,带上验货记录ID作为编辑模式
  router.push(`/inspection?edit=${record.id}`)
}

// 生命周期
onMounted(() => {
  fetchRecords()
})
</script>

<style scoped>
.inspection-records-view {
  min-height: 100vh;
  background-color: #f5f7fa;
  padding: 20px;
}

.container {
  max-width: 1200px;
  margin: 0 auto;
}

.header-section {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24px;
}

.page-title {
  font-size: 28px;
  font-weight: bold;
  margin: 0;
  color: #303133;
}

.start-btn {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 16px;
  padding: 12px 24px;
}

.filter-card {
  margin-bottom: 20px;
}

.filter-form {
  margin-bottom: 0;
}

.records-list {
  min-height: 300px;
}

.pagination {
  margin-top: 20px;
  display: flex;
  justify-content: center;
}

/* iPad 优化 */
@media (min-width: 768px) {
  .inspection-records-view {
    padding: 40px 20px;
  }
  
  .page-title {
    font-size: 32px;
  }
  
  .start-btn {
    font-size: 18px;
    padding: 14px 28px;
  }
}

/* 移动端优化 */
@media (max-width: 767px) {
  .inspection-records-view {
    padding: 16px;
  }
  
  .header-section {
    flex-direction: column;
    align-items: stretch;
    gap: 16px;
  }
  
  .page-title {
    font-size: 24px;
    text-align: center;
  }
  
  .start-btn {
    width: 100%;
    justify-content: center;
  }
  
  .filter-form :deep(.el-form-item) {
    display: block;
    margin-right: 0;
  }
  
  .filter-form :deep(.el-form-item__content) {
    display: block;
  }
  
  .filter-form :deep(.el-input),
  .filter-form :deep(.el-select) {
    width: 100%;
  }
}
</style>
