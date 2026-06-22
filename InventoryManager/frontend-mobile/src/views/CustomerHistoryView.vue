<template>
  <div class="customer-history-page">
    <van-nav-bar
      :title="view === 'search' ? '客户历史订单' : (selectedCustomer?.customer_name || '历史订单')"
      left-text="返回"
      left-arrow
      @click-left="onBack"
    />

    <!-- 搜索视图 -->
    <div v-if="view === 'search'" class="search-view">
      <van-search
        v-model="keyword"
        placeholder="电话 / 姓名 / 闲鱼ID（模糊匹配）"
        shape="round"
        @update:model-value="onKeywordInput"
        @search="doSearch"
      />

      <van-empty v-if="!searching && candidates.length === 0 && keyword" description="未找到匹配的客户" />

      <van-loading v-if="searching" class="loading-block">搜索中…</van-loading>

      <van-cell-group v-if="candidates.length > 0" inset>
        <van-cell
          v-for="(c, idx) in candidates"
          :key="idx"
          is-link
          @click="pickCustomer(c)"
        >
          <template #title>
            <div class="cust-line1">
              <span class="cust-name">{{ c.customer_name || '未填写' }}</span>
              <van-tag plain type="primary" class="count-tag">{{ c.total_rentals }} 单</van-tag>
            </div>
          </template>
          <template #label>
            <span class="phone">{{ c.customer_phone_masked || c.customer_phone || '' }}</span>
            <span v-if="c.buyer_id" class="buyer-id">闲鱼ID: {{ c.buyer_id }}</span>
          </template>
        </van-cell>
      </van-cell-group>
    </div>

    <!-- 历史明细视图 -->
    <div v-else class="detail-view">
      <van-loading v-if="loadingDetail" class="loading-block">加载中…</van-loading>
      <van-empty v-else-if="rentals.length === 0" description="该客户暂无历史订单" />

      <div v-for="r in rentals" :key="r.id" class="rental-card">
        <div class="card-header">
          <span class="model">{{ r.device_model_display_name || '-' }}</span>
          <van-tag v-if="r.lens_combo_display" type="primary" plain>{{ r.lens_combo_display }}</van-tag>
        </div>
        <div class="card-body">
          <div class="row">
            <span class="lbl">租赁价格</span>
            <span class="val money" v-if="r.order_amount != null">¥{{ r.order_amount.toFixed(2) }}</span>
            <span class="val muted" v-else>-</span>
          </div>
          <div class="row">
            <span class="lbl">日均价</span>
            <span class="val daily" v-if="dailyAvg(r) != null">¥{{ dailyAvg(r)!.toFixed(2) }}</span>
            <span class="val muted" v-else>-</span>
          </div>
          <div class="row">
            <span class="lbl">起止</span>
            <span class="val">{{ r.start_date }} ~ {{ r.end_date }}</span>
          </div>
          <div class="row">
            <span class="lbl">天数</span>
            <span class="val">{{ r.duration_days }} 天</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import axios from 'axios'
import { showFailToast } from 'vant'

interface CustomerSearchResult {
  customer_name: string
  customer_phone: string
  customer_phone_masked: string
  buyer_id: string
  total_rentals: number
}
interface CustomerRentalSummary {
  id: number
  device_model_name: string | null
  device_model_display_name: string
  lens_combo: string | null
  lens_combo_display: string
  order_amount: number | null
  start_date: string | null
  end_date: string | null
  duration_days: number
}

const router = useRouter()

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
    const { data } = await axios.get('/api/customers/search', { params: { q } })
    candidates.value = data?.success ? (data.data?.customers ?? []) : []
  } catch (e) {
    showFailToast('搜索失败')
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
    const { data } = await axios.get('/api/customers/rentals', {
      params: {
        phone: row.customer_phone || undefined,
        name: row.customer_name || undefined,
        buyer_id: row.buyer_id || undefined,
        limit: 5,
      }
    })
    rentals.value = data?.success ? (data.data?.rentals ?? []) : []
  } catch (e) {
    showFailToast('加载历史订单失败')
  } finally {
    loadingDetail.value = false
  }
}

const dailyAvg = (row: CustomerRentalSummary) => {
  if (row.order_amount == null || !row.duration_days) return null
  return row.order_amount / row.duration_days
}

const onBack = () => {
  if (view.value === 'detail') {
    view.value = 'search'
  } else {
    router.back()
  }
}
</script>

<style scoped>
.customer-history-page { min-height: 100vh; background: #f7f8fa; padding-bottom: 30px; }
.search-view, .detail-view { padding-top: 8px; }
.loading-block { text-align: center; padding: 24px; }
.cust-line1 { display: flex; gap: 8px; align-items: center; }
.cust-name { font-weight: 600; }
.count-tag { font-size: 11px; }
.phone { color: #646566; margin-right: 12px; }
.buyer-id { color: #969799; font-size: 12px; }

.rental-card {
  margin: 10px 12px;
  background: #fff;
  border-radius: 10px;
  padding: 12px 14px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.04);
}
.card-header {
  display: flex; align-items: center; gap: 10px;
  font-weight: 600; font-size: 15px; margin-bottom: 8px;
}
.card-header .model { flex: 1; }
.card-body .row { display: flex; justify-content: space-between; padding: 4px 0; font-size: 14px; }
.card-body .lbl { color: #969799; }
.card-body .val { color: #323233; }
.money { color: #ee0a24; font-weight: 600; }
.daily { color: #07c160; font-weight: 600; }
.muted { color: #c8c9cc; }
</style>
