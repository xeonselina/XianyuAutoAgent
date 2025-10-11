<template>
  <div class="statistics-page">
    <div class="page-header">
      <h1>租赁数据统计</h1>
      <el-button @click="goBack" type="primary">
        <el-icon><ArrowLeft /></el-icon>
        返回首页
      </el-button>
    </div>

    <div class="statistics-content">
      <!-- 数据卡片 -->
      <div class="stats-cards">
        <el-card v-if="latestStat">
          <template #header>
            <span>最新统计 ({{ latestStat.stat_date }})</span>
          </template>
          <div class="stat-item">
            <span>订单数：</span>
            <strong>{{ latestStat.total_rentals }}</strong>
          </div>
          <div class="stat-item">
            <span>总租金：</span>
            <strong>¥{{ latestStat.total_rent.toFixed(2) }}</strong>
          </div>
          <div class="stat-item">
            <span>总收入：</span>
            <strong>¥{{ latestStat.total_value.toFixed(2) }}</strong>
          </div>
        </el-card>
      </div>

      <!-- 图表容器 -->
      <el-card class="chart-card">
        <template #header>
          <span>最近30天趋势图</span>
        </template>
        <div ref="chartContainer" style="width: 100%; height: 400px;"></div>
      </el-card>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ArrowLeft } from '@element-plus/icons-vue'
import * as echarts from 'echarts'

const router = useRouter()
const chartContainer = ref<HTMLElement>()
const latestStat = ref<any>(null)
const statsData = ref<any[]>([])

const goBack = () => {
  router.push('/gantt')
}

const fetchStatistics = async () => {
  try {
    // 获取最新统计
    const latestRes = await fetch('/api/statistics/latest')
    const latestData = await latestRes.json()
    if (latestData.success) {
      latestStat.value = latestData.data
    }

    // 获取最近30天统计
    const recentRes = await fetch('/api/statistics/recent?days=30')
    const recentData = await recentRes.json()
    if (recentData.success) {
      statsData.value = recentData.data
      renderChart()
    }
  } catch (error) {
    console.error('获取统计数据失败:', error)
  }
}

const renderChart = () => {
  if (!chartContainer.value || statsData.value.length === 0) return

  const chart = echarts.init(chartContainer.value)

  const dates = statsData.value.map(item => item.stat_date)
  const rentals = statsData.value.map(item => item.total_rentals)
  const values = statsData.value.map(item => item.total_value)

  const option = {
    title: {
      text: '租赁数据趋势'
    },
    tooltip: {
      trigger: 'axis'
    },
    legend: {
      data: ['订单数', '收入价值']
    },
    xAxis: {
      type: 'category',
      data: dates,
      axisLabel: {
        rotate: 45
      }
    },
    yAxis: [
      {
        type: 'value',
        name: '订单数',
        position: 'left'
      },
      {
        type: 'value',
        name: '收入 (¥)',
        position: 'right'
      }
    ],
    series: [
      {
        name: '订单数',
        type: 'line',
        data: rentals,
        smooth: true
      },
      {
        name: '收入价值',
        type: 'line',
        yAxisIndex: 1,
        data: values,
        smooth: true
      }
    ]
  }

  chart.setOption(option)

  // 响应式调整
  window.addEventListener('resize', () => {
    chart.resize()
  })
}

onMounted(() => {
  fetchStatistics()
})
</script>

<style scoped>
.statistics-page {
  padding: 20px;
  background: #f5f5f5;
  min-height: 100vh;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
  background: white;
  padding: 20px;
  border-radius: 8px;
}

.page-header h1 {
  margin: 0;
}

.statistics-content {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.stats-cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
  gap: 20px;
}

.stat-item {
  display: flex;
  justify-content: space-between;
  padding: 10px 0;
  border-bottom: 1px solid #eee;
}

.stat-item:last-child {
  border-bottom: none;
}

.chart-card {
  min-height: 500px;
}
</style>
