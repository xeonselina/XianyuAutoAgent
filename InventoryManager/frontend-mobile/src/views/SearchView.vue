<template>
  <div class="search-view">
    <van-nav-bar
      title="搜索租赁记录"
      left-arrow
      @click-left="$router.back()"
      :border="false"
    />

    <!-- 搜索框 -->
    <van-search
      v-model="keyword"
      placeholder="输入客户电话或收货地址"
      autofocus
      show-action
      action-text="搜索"
      @search="doSearch"
      @update:model-value="onInput"
    />

    <!-- 结果列表 -->
    <div class="result-body">
      <!-- 加载中 -->
      <div v-if="loading" class="center-tip">
        <van-loading color="#409eff" />
      </div>

      <!-- 空状态 -->
      <div v-else-if="searched && !results.length" class="center-tip">
        <van-empty description="未找到相关记录" />
      </div>

      <!-- 提示未搜索 -->
      <div v-else-if="!searched" class="center-tip hint-text">
        输入电话或地址关键词进行搜索
      </div>

      <!-- 结果列表 -->
      <van-cell-group v-else inset>
        <van-cell
          v-for="rental in results"
          :key="rental.id"
          clickable
          @click="goEdit(rental.id)"
        >
          <template #title>
            <div class="result-title">
              <span class="customer-name">{{ rental.customer_name }}</span>
              <van-tag :color="STATUS_COLORS[rental.status]" text-color="#fff">
                {{ STATUS_LABELS[rental.status] || rental.status }}
              </van-tag>
            </div>
          </template>
          <template #label>
            <div class="result-label">
              <span class="phone">📱 {{ rental.customer_phone || '-' }}</span>
              <span class="dates">{{ rental.start_date }} → {{ rental.end_date }}</span>
            </div>
            <div class="address" v-if="rental.destination">
              📍 {{ rental.destination }}
            </div>
          </template>
        </van-cell>
      </van-cell-group>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import axios from 'axios'

const router = useRouter()

const keyword = ref('')
const results = ref<any[]>([])
const loading = ref(false)
const searched = ref(false)

let debounceTimer: ReturnType<typeof setTimeout> | null = null

const STATUS_LABELS: Record<string, string> = {
  not_shipped:            '待发货',
  scheduled_for_shipping: '已预约',
  shipped:                '已发货',
  returned:               '已还租',
  completed:              '已完成',
  cancelled:              '已取消',
}

const STATUS_COLORS: Record<string, string> = {
  not_shipped:            '#c8860a',
  scheduled_for_shipping: '#1989fa',
  shipped:                '#07c160',
  returned:               '#7232dd',
  completed:              '#909399',
  cancelled:              '#c8c9cc',
}

const doSearch = async () => {
  const q = keyword.value.trim()
  if (!q) return
  loading.value = true
  searched.value = true
  try {
    const res = await axios.post('/api/rentals/search', { q, per_page: 50 })
    if (res.data.success) {
      results.value = res.data.data?.rentals ?? res.data.data?.items ?? res.data.data ?? []
    } else {
      results.value = []
    }
  } catch {
    results.value = []
  } finally {
    loading.value = false
  }
}

const onInput = () => {
  if (debounceTimer) clearTimeout(debounceTimer)
  if (!keyword.value.trim()) {
    searched.value = false
    results.value = []
    return
  }
  debounceTimer = setTimeout(doSearch, 400)
}

const goEdit = (id: number) => {
  router.push({ name: 'edit-rental', params: { id } })
}
</script>

<style scoped>
.search-view {
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: #f5f5f5;
}

.result-body {
  flex: 1;
  overflow-y: auto;
  -webkit-overflow-scrolling: touch;
  padding-top: 8px;
}

.center-tip {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 60px 0;
}

.hint-text {
  font-size: 13px;
  color: #999;
}

.result-title {
  display: flex;
  align-items: center;
  gap: 6px;
}

.customer-name {
  font-weight: 600;
  font-size: 14px;
  color: #333;
}

.result-label {
  display: flex;
  gap: 12px;
  margin-top: 2px;
  font-size: 12px;
  color: #666;
}

.address {
  font-size: 11px;
  color: #999;
  margin-top: 2px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
</style>
