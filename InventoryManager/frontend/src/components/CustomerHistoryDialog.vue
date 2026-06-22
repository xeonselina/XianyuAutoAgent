<template>
  <el-dialog
    v-model="visible"
    title="客户历史订单"
    width="720px"
    :close-on-click-modal="false"
    @close="reset"
  >
    <!-- 搜索视图 -->
    <div v-if="view === 'search'" class="search-view">
      <el-input
        v-model="keyword"
        placeholder="输入电话 / 姓名 / 闲鱼ID（模糊匹配）"
        clearable
        @input="onKeywordInput"
        @keyup.enter="doSearch"
      >
        <template #prefix>
          <el-icon><Search /></el-icon>
        </template>
        <template #append>
          <el-button @click="doSearch">搜索</el-button>
        </template>
      </el-input>

      <div v-loading="searching" class="result-list">
        <el-empty v-if="!searching && candidates.length === 0 && keyword" description="未找到匹配的客户" />
        <el-table
          v-if="candidates.length > 0"
          :data="candidates"
          stripe
          highlight-current-row
          @row-click="pickCustomer"
          style="margin-top: 12px"
        >
          <el-table-column prop="customer_name" label="姓名" min-width="120" />
          <el-table-column label="电话" min-width="120">
            <template #default="{ row }">{{ row.customer_phone_masked || row.customer_phone || '-' }}</template>
          </el-table-column>
          <el-table-column prop="buyer_id" label="闲鱼ID" min-width="160" show-overflow-tooltip />
          <el-table-column prop="total_rentals" label="历史单数" width="100" align="center" />
        </el-table>
        <div v-if="candidates.length > 0" class="hint">点击行查看历史订单</div>
      </div>
    </div>

    <!-- 历史明细视图 -->
    <div v-else class="detail-view">
      <div class="detail-header">
        <el-button @click="view = 'search'" :icon="ArrowLeft" link>返回搜索</el-button>
        <span class="customer-summary">
          <b>{{ selectedCustomer?.customer_name || '未填写' }}</b>
          <span class="phone">{{ selectedCustomer?.customer_phone_masked || selectedCustomer?.customer_phone || '' }}</span>
          <span v-if="selectedCustomer?.buyer_id" class="buyer-id">闲鱼ID: {{ selectedCustomer.buyer_id }}</span>
        </span>
      </div>

      <el-table v-loading="loadingDetail" :data="rentals" stripe :empty-text="loadingDetail ? '加载中...' : '该客户暂无历史订单'">
        <el-table-column label="机型 · 镜头组合" min-width="180">
          <template #default="{ row }">
            <span class="model-cell">{{ row.device_model_display_name || '-' }}</span>
            <el-tag v-if="row.lens_combo_display" size="small" type="info" class="combo-tag">
              {{ row.lens_combo_display }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="租赁价格" width="110" align="right">
          <template #default="{ row }">
            <span v-if="row.order_amount != null" class="money">¥{{ row.order_amount.toFixed(2) }}</span>
            <span v-else class="muted">-</span>
          </template>
        </el-table-column>
        <el-table-column label="开始" prop="start_date" width="120" />
        <el-table-column label="结束" prop="end_date" width="120" />
        <el-table-column label="天数" width="70" align="center">
          <template #default="{ row }">{{ row.duration_days }} 天</template>
        </el-table-column>
        <el-table-column label="日均价 (参考)" width="120" align="right">
          <template #default="{ row }">
            <span v-if="dailyAvg(row) != null" class="daily">¥{{ dailyAvg(row)!.toFixed(2) }}</span>
            <span v-else class="muted">-</span>
          </template>
        </el-table-column>
      </el-table>
    </div>
  </el-dialog>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Search, ArrowLeft } from '@element-plus/icons-vue'
import {
  searchCustomers,
  getCustomerRentals,
  type CustomerSearchResult,
  type CustomerRentalSummary,
} from '../api/customerApi'

const props = defineProps<{ modelValue: boolean }>()
const emit = defineEmits<{ (e: 'update:modelValue', v: boolean): void }>()

const visible = ref(props.modelValue)
watch(() => props.modelValue, (v) => (visible.value = v))
watch(visible, (v) => emit('update:modelValue', v))

const view = ref<'search' | 'detail'>('search')
const keyword = ref('')
const candidates = ref<CustomerSearchResult[]>([])
const searching = ref(false)
const selectedCustomer = ref<CustomerSearchResult | null>(null)
const rentals = ref<CustomerRentalSummary[]>([])
const loadingDetail = ref(false)

let debounceTimer: number | null = null

const onKeywordInput = () => {
  if (debounceTimer) window.clearTimeout(debounceTimer)
  debounceTimer = window.setTimeout(doSearch, 300)
}

const doSearch = async () => {
  const q = keyword.value.trim()
  if (!q) {
    candidates.value = []
    return
  }
  searching.value = true
  try {
    candidates.value = await searchCustomers(q)
  } catch (e: any) {
    ElMessage.error('搜索失败')
    console.error(e)
  } finally {
    searching.value = false
  }
}

const pickCustomer = async (row: CustomerSearchResult) => {
  selectedCustomer.value = row
  view.value = 'detail'
  loadingDetail.value = true
  rentals.value = []
  try {
    rentals.value = await getCustomerRentals({
      phone: row.customer_phone || undefined,
      name: row.customer_name || undefined,
      buyer_id: row.buyer_id || undefined,
      limit: 5,
    })
  } catch (e: any) {
    ElMessage.error('加载历史订单失败')
    console.error(e)
  } finally {
    loadingDetail.value = false
  }
}

const dailyAvg = (row: CustomerRentalSummary) => {
  if (row.order_amount == null || !row.duration_days) return null
  return row.order_amount / row.duration_days
}

const reset = () => {
  view.value = 'search'
  keyword.value = ''
  candidates.value = []
  selectedCustomer.value = null
  rentals.value = []
}
</script>

<style scoped>
.result-list { min-height: 200px; }
.hint { color: #909399; font-size: 12px; margin-top: 8px; }
.detail-header {
  display: flex;
  align-items: center;
  gap: 16px;
  padding-bottom: 12px;
  margin-bottom: 12px;
  border-bottom: 1px dashed #e4e7ed;
}
.customer-summary {
  display: inline-flex; gap: 12px; align-items: center; flex-wrap: wrap;
}
.customer-summary .phone { color: #606266; }
.customer-summary .buyer-id { color: #909399; font-size: 12px; }
.combo-tag { margin-left: 8px; }
.model-cell { font-weight: 500; }
.money { color: #e6a23c; font-weight: 600; }
.daily { color: #67c23a; font-weight: 600; }
.muted { color: #c0c4cc; }

/* 响应式：窄屏减小 dialog 内边距 */
@media (max-width: 768px) {
  :deep(.el-dialog) { width: 95vw !important; }
}
</style>
