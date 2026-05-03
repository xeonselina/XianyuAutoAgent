<template>
  <div class="rental-stats-page">
    <!-- 顶部工具栏 -->
    <div class="page-header">
      <div class="header-left">
        <el-button @click="goBack" :icon="ArrowLeft">返回首页</el-button>
        <h2>出租周期统计</h2>
      </div>
      <div class="header-controls">
        <el-radio-group v-model="periodType" @change="fetchStats" size="small">
          <el-radio-button value="week">按周</el-radio-button>
          <el-radio-button value="month">按月</el-radio-button>
        </el-radio-group>
        <el-select v-model="modelFilter" @change="fetchStats" size="small" style="width: 160px">
          <el-option label="全部型号" value="all" />
          <el-option
            v-for="m in modelOptions"
            :key="m.id"
            :label="m.display_name"
            :value="m.id"
          />
        </el-select>
        <el-date-picker
          v-model="dateRange"
          type="daterange"
          range-separator="至"
          start-placeholder="开始日期"
          end-placeholder="结束日期"
          size="small"
          format="YYYY-MM-DD"
          value-format="YYYY-MM-DD"
          style="width: 240px"
          @change="fetchStats"
        />
        <el-button type="success" size="small" :icon="Download" @click="exportCsv">导出 CSV</el-button>
      </div>
    </div>

    <!-- 出租率色块说明 -->
    <div class="legend-bar">
      <span class="legend-item"><span class="dot dot-green" />出租率 ≥ 80%（优秀）</span>
      <span class="legend-item"><span class="dot dot-yellow" />50% ≤ 出租率 &lt; 80%（良好）</span>
      <span class="legend-item"><span class="dot dot-red" />出租率 &lt; 50%（待提升）</span>
    </div>

    <!-- 周期统计表格 -->
    <el-card v-loading="loading" class="table-card">
      <template #header>
        <span class="card-title">
          {{ periodType === 'week' ? '按周' : '按月' }} · {{ modelLabel }} 出租数据
        </span>
      </template>

      <el-table
        :data="statsData"
        border
        stripe
        style="width: 100%"
        :summary-method="getSummary"
        show-summary
      >
        <el-table-column prop="period" :label="periodType === 'week' ? '周（起始日）' : '月份'" min-width="120" fixed />
        <el-table-column prop="device_count" label="设备数（台）" min-width="100" align="center" />
        <el-table-column prop="order_count" label="订单数" min-width="80" align="center" />
        <el-table-column :label="periodType === 'week' ? '出租率（订单/台）' : '出租率（订单/台/周）'" min-width="140" align="center">
          <template #default="{ row }">
            <el-tag
              :type="getRentalRateTagType(row.rental_rate)"
              :style="getRentalRateStyle(row.rental_rate)"
              effect="dark"
              size="small"
            >
              {{ formatPercent(row.rental_rate) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="order_amount" label="订单金额（元）" min-width="120" align="right">
          <template #default="{ row }">
            {{ formatMoney(row.order_amount) }}
          </template>
        </el-table-column>
        <el-table-column prop="avg_revenue_per_device" label="均收入/台（元）" min-width="120" align="right">
          <template #default="{ row }">
            {{ formatMoney(row.avg_revenue_per_device) }}
          </template>
        </el-table-column>
        <el-table-column prop="profit" label="预计收益（元）" min-width="120" align="right">
          <template #default="{ row }">
            {{ formatMoney(row.profit) }}
          </template>
        </el-table-column>
        <el-table-column prop="depreciation" label="预估折旧（元）" min-width="120" align="right">
          <template #default="{ row }">
            <span class="text-loss">-{{ formatMoney(row.depreciation) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="net_profit" label="预估利润（元）" min-width="120" align="right">
          <template #default="{ row }">
            <span :class="row.net_profit >= 0 ? 'text-profit' : 'text-loss'">
              {{ formatMoney(row.net_profit) }}
            </span>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- x200u 年化收益率预测表 -->
    <el-card v-loading="forecastLoading" class="table-card forecast-card">
      <template #header>
        <div class="forecast-header">
          <span class="card-title">x200u 累计年化收益率预测（5月–8月）</span>
          <div class="forecast-meta">
            <el-tag size="small" type="info">设备数：{{ forecastData?.device_count ?? '—' }} 台</el-tag>
            <el-tag size="small" type="info">购买价：¥{{ forecastData?.purchase_price ?? '—' }}/台</el-tag>
            <el-tag size="small" type="info">总成本：¥{{ forecastData?.total_cost ?? '—' }}</el-tag>
            <el-tag size="small" type="success">历史净利润：¥{{ forecastData?.hist_net_profit != null ? formatMoney(forecastData.hist_net_profit) : '—' }}</el-tag>
            <el-tag size="small" type="warning">5月预测单价：¥{{ forecastData?.avg_order_amount ?? '—' }}（单价趋势斜率 {{ forecastData?.price_slope ?? '—' }}/月）</el-tag>
          </div>
        </div>
      </template>

      <div v-if="forecastData" class="scenario-tabs">
        <el-tabs v-model="activeScenario" type="border-card">
          <el-tab-pane
            v-for="(scenario, name) in forecastData.scenarios"
            :key="name"
            :label="getScenarioLabel(String(name), scenario.rental_rate)"
            :name="name"
          >
            <el-table
              :data="scenario.months"
              border
              stripe
              style="width: 100%"
              :summary-method="getForecastSummary(scenario)"
              show-summary
            >
              <el-table-column prop="month" label="月份" min-width="100" />
              <el-table-column prop="device_count" label="设备数" min-width="70" align="center" />
              <el-table-column label="出租率" min-width="80" align="center">
                <template #default="{ row }">
                  <el-tag :style="getRentalRateStyle(row.rental_rate)" effect="dark" size="small">
                    {{ formatPercent(row.rental_rate) }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="avg_order_price" label="预测单价（元）" min-width="110" align="right">
                <template #default="{ row }">
                  ¥{{ formatMoney(row.avg_order_price) }}
                </template>
              </el-table-column>
              <el-table-column prop="orders_per_device" label="单台订单数/月" min-width="110" align="center" />
              <el-table-column label="单台月租金收入" min-width="120" align="right">
                <template #default="{ row }">{{ formatMoney(row.revenue_per_device) }}</template>
              </el-table-column>
              <el-table-column label="全部折旧" min-width="100" align="right">
                <template #default="{ row }">
                  <span class="text-loss">-{{ formatMoney(row.depreciation_total) }}</span>
                </template>
              </el-table-column>
              <el-table-column label="当月净收益" min-width="110" align="right">
                <template #default="{ row }">
                  <span :class="row.monthly_net >= 0 ? 'text-profit' : 'text-loss'">
                    {{ formatMoney(row.monthly_net) }}
                  </span>
                </template>
              </el-table-column>
              <el-table-column label="累计净利润" min-width="120" align="right">
                <template #default="{ row }">
                  <strong :class="row.cumulative_net >= 0 ? 'text-profit' : 'text-loss'">
                    {{ formatMoney(row.cumulative_net) }}
                  </strong>
                </template>
              </el-table-column>
              <el-table-column label="累计年化收益率" min-width="130" align="center">
                <template #default="{ row }">
                  <el-tag
                    :type="row.cum_annualized_roi >= 20 ? 'success' : row.cum_annualized_roi >= 10 ? 'warning' : 'danger'"
                    effect="dark"
                    size="small"
                  >
                    {{ row.cum_annualized_roi.toFixed(1) }}%
                  </el-tag>
                </template>
              </el-table-column>
            </el-table>

            <!-- 场景汇总卡片 -->
            <div class="scenario-summary">
              <div class="summary-item">
                <div class="s-label">历史净利润（至上月末）</div>
                <div class="s-value text-profit">¥{{ formatMoney(scenario.hist_net_profit) }}</div>
              </div>
              <div class="summary-item">
                <div class="s-label">8月末累计净利润</div>
                <div class="s-value" :class="scenario.total_net_at_aug_end >= 0 ? 'text-profit' : 'text-loss'">
                  ¥{{ formatMoney(scenario.total_net_at_aug_end) }}
                </div>
              </div>
              <div class="summary-item">
                <div class="s-label">8月末累计年化收益率</div>
                <div class="s-value roi-value">{{ scenario.cum_annualized_roi_at_aug_end.toFixed(1) }}%</div>
              </div>
            </div>
          </el-tab-pane>
        </el-tabs>
      </div>

      <div v-else-if="!forecastLoading" class="no-data">
        <el-empty description="暂无预测数据" />
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ArrowLeft, Download } from '@element-plus/icons-vue'

const router = useRouter()

// ── 周期统计 ─────────────────────────────────────
const periodType = ref<'week' | 'month'>('month')
const modelFilter = ref<number | 'all'>('all')
const modelOptions = ref<{ id: number; name: string; display_name: string }[]>([])
const dateRange = ref<[string, string] | null>(null)
const loading = ref(false)
const statsData = ref<any[]>([])
const summary = ref<any>(null)

const modelLabel = computed(() => {
  if (modelFilter.value === 'all') return '全部型号'
  const m = modelOptions.value.find(x => x.id === modelFilter.value)
  return m ? m.display_name : String(modelFilter.value)
})

// ── 年化预测 ─────────────────────────────────────
const forecastLoading = ref(false)
const forecastData = ref<any>(null)
const activeScenario = ref('中立')

const goBack = () => router.push('/')

// ── 颜色逻辑 ─────────────────────────────────────
function getRentalRateTagType(rate: number) {
  if (rate >= 0.8) return 'success'
  if (rate >= 0.5) return 'warning'
  return 'danger'
}

function getRentalRateStyle(rate: number) {
  if (rate >= 0.8) return { background: '#67c23a', borderColor: '#67c23a', color: '#fff' }
  if (rate >= 0.5) return { background: '#e6a23c', borderColor: '#e6a23c', color: '#fff' }
  return { background: '#f56c6c', borderColor: '#f56c6c', color: '#fff' }
}

// ── 格式化 ────────────────────────────────────────
function formatPercent(val: number) {
  return `${(val * 100).toFixed(1)}%`
}
function formatMoney(val: number) {
  return val.toFixed(2)
}

// ── 型号列表 ──────────────────────────────────────
async function fetchModels() {
  try {
    const res = await fetch('/api/rental-stats/models')
    const json = await res.json()
    if (json.success) {
      modelOptions.value = json.data
    }
  } catch (e) {
    console.error('获取型号列表失败', e)
  }
}

// ── 数据获取 ──────────────────────────────────────
async function fetchStats() {
  loading.value = true
  try {
    const params = new URLSearchParams({
      period_type: periodType.value,
      model: modelFilter.value === 'all' ? 'all' : String(modelFilter.value),
    })
    if (dateRange.value) {
      params.set('start_date', dateRange.value[0])
      params.set('end_date', dateRange.value[1])
    }
    const res = await fetch(`/api/rental-stats/periodic?${params}`)
    const json = await res.json()
    if (json.success) {
      statsData.value = json.data
      summary.value = json.summary
    }
  } catch (e) {
    console.error('获取统计数据失败', e)
  } finally {
    loading.value = false
  }
}

async function fetchForecast() {
  forecastLoading.value = true
  try {
    const res = await fetch('/api/rental-stats/x200u-forecast')
    const json = await res.json()
    if (json.success) {
      forecastData.value = json
    }
  } catch (e) {
    console.error('获取预测数据失败', e)
  } finally {
    forecastLoading.value = false
  }
}

// ── 表格 footer ───────────────────────────────────
function getSummary({ columns }: { columns: any[] }) {
  const s = summary.value
  if (!s) return []
  return columns.map((col: any, idx: number) => {
    if (idx === 0) return '汇总'
    if (col.property === 'order_count') return `总计 ${s.total_orders}`
    if (col.property === 'rental_rate') return `均 ${formatPercent(s.avg_rental_rate)}`
    if (col.property === 'order_amount') return `¥${formatMoney(s.total_order_amount)}`
    if (col.property === 'avg_revenue_per_device') return `均 ¥${formatMoney(s.avg_revenue_per_device)}`
    if (col.property === 'profit') return `¥${formatMoney(s.total_profit)}`
    if (col.property === 'depreciation') return `-¥${formatMoney(s.total_depreciation)}`
    if (col.property === 'net_profit') return `¥${formatMoney(s.total_net_profit)}`
    return ''
  })
}

function getForecastSummary(scenario: any) {
  return ({ columns }: { columns: any[] }) => {
    return columns.map((col: any, idx: number) => {
      if (idx === 0) return '8月汇总'
      if (col.property === 'cumulative_net') return `¥${formatMoney(scenario.total_net_at_aug_end)}`
      if (col.property === 'cum_annualized_roi') return `${scenario.cum_annualized_roi_at_aug_end.toFixed(1)}%`
      return ''
    })
  }
}

// ── CSV 导出 ───────────────────────────────────────
function exportCsv() {
  if (!statsData.value.length) return
  const headers = ['周期', '设备数', '订单数', '出租率', '订单金额', '均收入/台', '预计收益', '预估折旧', '预估利润']
  const rows = statsData.value.map(r => [
    r.period,
    r.device_count,
    r.order_count,
    formatPercent(r.rental_rate),
    r.order_amount,
    r.avg_revenue_per_device,
    r.profit,
    r.depreciation,
    r.net_profit,
  ])
  const s = summary.value
  if (s) {
    rows.push(['汇总', '', s.total_orders, formatPercent(s.avg_rental_rate), s.total_order_amount, s.avg_revenue_per_device, s.total_profit, s.total_depreciation, s.total_net_profit])
  }
  const csv = [headers, ...rows].map(row => row.join(',')).join('\n')
  const blob = new Blob(['﻿' + csv], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `出租统计_${periodType.value}_${modelFilter.value}_${new Date().toISOString().slice(0, 10)}.csv`
  a.click()
  URL.revokeObjectURL(url)
}

// ── 场景 label ────────────────────────────────────
function getScenarioLabel(name: string, rate: number) {
  return `${name}预期（出租率 ${formatPercent(rate)}）`
}

onMounted(() => {
  fetchModels()
  fetchStats()
  fetchForecast()
})
</script>

<style scoped>
.rental-stats-page {
  padding: 16px;
  background: #f0f2f5;
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: #fff;
  padding: 14px 20px;
  border-radius: 8px;
  box-shadow: 0 1px 4px rgba(0,0,0,.08);
  flex-wrap: wrap;
  gap: 12px;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}
.header-left h2 {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
  color: #303133;
}

.header-controls {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.legend-bar {
  display: flex;
  gap: 24px;
  background: #fff;
  padding: 10px 20px;
  border-radius: 8px;
  box-shadow: 0 1px 4px rgba(0,0,0,.06);
  font-size: 13px;
  color: #606266;
  flex-wrap: wrap;
}
.legend-item {
  display: flex;
  align-items: center;
  gap: 6px;
}
.dot {
  display: inline-block;
  width: 12px;
  height: 12px;
  border-radius: 50%;
}
.dot-green  { background: #67c23a; }
.dot-yellow { background: #e6a23c; }
.dot-red    { background: #f56c6c; }

.table-card {
  border-radius: 8px;
}

.card-title {
  font-weight: 600;
  font-size: 15px;
}

.text-profit { color: #67c23a; font-weight: 600; }
.text-loss   { color: #f56c6c; font-weight: 600; }

/* 预测卡片 */
.forecast-card { margin-top: 0; }

.forecast-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}
.forecast-meta { display: flex; gap: 8px; flex-wrap: wrap; }

.scenario-tabs :deep(.el-tabs__content) { padding: 16px 0 0 0; }

.scenario-summary {
  display: flex;
  gap: 24px;
  margin-top: 16px;
  padding: 14px 20px;
  background: #f5f7fa;
  border-radius: 6px;
  flex-wrap: wrap;
}
.summary-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 160px;
}
.s-label {
  font-size: 12px;
  color: #909399;
}
.s-value {
  font-size: 20px;
  font-weight: 700;
  color: #303133;
}
.roi-value {
  color: #409eff;
}
</style>
