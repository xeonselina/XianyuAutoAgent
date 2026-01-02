<template>
  <div class="mobile-date-header">
    <!-- 日期标题行 (可横向滚动) -->
    <div class="date-header-scroll-container">
      <div class="date-header-row">
        <div
          v-for="(date, index) in dateArray"
          :key="date.toString()"
          class="date-col"
          :class="{
            'is-today': isToday(date),
            'is-weekend': isWeekend(date),
            'month-start': isFirstDayOfMonth(date)
          }"
        >
          <!-- 月份分隔 -->
          <div v-if="isFirstDayOfMonth(date)" class="month-divider">
            <span class="month-label">{{ formatMonth(date) }}</span>
          </div>

          <!-- 日期信息 -->
          <div class="date-day">{{ formatDay(date) }}</div>
          <div class="date-weekday">{{ formatWeekday(date) }}</div>

          <!-- 每日统计 -->
          <div class="date-stats">
            <span v-if="getStats(date).shipOut > 0" class="stat-ship">
              {{ getStats(date).shipOut }}寄
            </span>
            <span v-if="getStats(date).available > 0" class="stat-idle">
              {{ getStats(date).available }}闲
            </span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useGanttStore } from '@/stores/gantt'
import dayjs from 'dayjs'
import axios from 'axios'
import type { Dayjs } from 'dayjs'

const ganttStore = useGanttStore()

// 日期数组(从当前开始日期到结束日期)
const dateArray = computed(() => {
  const dates: Date[] = []
  const start = dayjs(ganttStore.currentStartDate)
  const end = dayjs(ganttStore.currentEndDate)

  let current = start
  while (current.isBefore(end) || current.isSame(end, 'day')) {
    dates.push(current.toDate())
    current = current.add(1, 'day')
  }

  return dates
})

// 每日统计数据
const dailyStats = ref<Record<string, { available: number; shipOut: number }>>({})

// 格式化函数
const formatDay = (date: Date) => dayjs(date).format('M/D')
const formatWeekday = (date: Date) => {
  const weekdays = ['日', '一', '二', '三', '四', '五', '六']
  return weekdays[dayjs(date).day()]
}
const formatMonth = (date: Date) => dayjs(date).format('M月')

// 判断函数
const isToday = (date: Date) => dayjs(date).isSame(dayjs(), 'day')
const isWeekend = (date: Date) => {
  const day = dayjs(date).day()
  return day === 0 || day === 6
}
const isFirstDayOfMonth = (date: Date) => dayjs(date).date() === 1

// 获取每日统计数据
const getStats = (date: Date) => {
  const dateStr = dayjs(date).format('YYYY-MM-DD')
  return dailyStats.value[dateStr] || { available: 0, shipOut: 0 }
}

// 加载每日统计数据
const loadDailyStats = async () => {
  try {
    const stats = await Promise.all(
      dateArray.value.map(async (date) => {
        const dateStr = dayjs(date).format('YYYY-MM-DD')

        try {
          const response = await axios.get('/api/gantt/daily-stats', {
            params: { date: dateStr }
          })

          if (response.data.success) {
            return {
              date: dateStr,
              available: response.data.data.available_count || 0,
              shipOut: response.data.data.ship_out_count || 0
            }
          }
        } catch (error) {
          console.error(`Failed to load stats for ${dateStr}:`, error)
        }

        return {
          date: dateStr,
          available: 0,
          shipOut: 0
        }
      })
    )

    // 将统计数据存储到响应式对象中
    const statsMap: Record<string, { available: number; shipOut: number }> = {}
    stats.forEach(stat => {
      statsMap[stat.date] = {
        available: stat.available,
        shipOut: stat.shipOut
      }
    })

    dailyStats.value = statsMap
  } catch (error) {
    console.error('加载每日统计失败:', error)
  }
}

// 监听日期范围变化
watch(() => [ganttStore.currentStartDate, ganttStore.currentEndDate], () => {
  loadDailyStats()
}, { deep: true })

// 生命周期
onMounted(() => {
  loadDailyStats()
})
</script>

<style scoped lang="scss">
.mobile-date-header {
  width: 100%;
  background: #f5f7fa;
  border-bottom: 2px solid #dcdfe6;
  position: sticky;
  top: 46px; // van-nav-bar height
  z-index: 10;
}

.date-header-scroll-container {
  overflow-x: auto;
  overflow-y: hidden;
  -webkit-overflow-scrolling: touch;

  &::-webkit-scrollbar {
    height: 4px;
  }

  &::-webkit-scrollbar-thumb {
    background: #c1c1c1;
    border-radius: 2px;
  }
}

.date-header-row {
  display: flex;
  min-width: 100%;
}

.date-col {
  min-width: 50px;
  flex-shrink: 0;
  text-align: center;
  padding: 8px 4px;
  border-right: 1px solid #ebeef5;
  position: relative;
  background: white;

  &.is-today {
    background: #e6f7ff;

    .date-day {
      color: #1890ff;
      font-weight: bold;
    }
  }

  &.is-weekend {
    background: #fff7e6;
  }

  &.month-start {
    border-left: 2px solid #ff6b6b;
  }
}

.month-divider {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 0;
}

.month-label {
  position: absolute;
  top: -18px;
  left: 50%;
  transform: translateX(-50%);
  background: #ff6b6b;
  color: white;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 10px;
  white-space: nowrap;
  z-index: 1;
}

.date-day {
  font-size: 12px;
  font-weight: 500;
  margin-bottom: 2px;
  color: #303133;
}

.date-weekday {
  font-size: 10px;
  color: #909399;
  margin-bottom: 4px;
}

.date-stats {
  font-size: 10px;
  white-space: nowrap;
  display: flex;
  flex-direction: column;
  gap: 2px;

  .stat-ship {
    color: #67c23a;
    font-size: 9px;
  }

  .stat-idle {
    color: #909399;
    font-size: 9px;
  }
}

/* 小屏幕适配 (iPhone SE: 320px) */
@media (max-width: 374px) {
  .date-col {
    min-width: 45px;
  }

  .date-day {
    font-size: 11px;
  }

  .date-stats {
    font-size: 9px;

    .stat-ship,
    .stat-idle {
      font-size: 8px;
    }
  }
}

/* Plus机型 (>430px) */
@media (min-width: 431px) {
  .date-col {
    min-width: 60px;
  }

  .date-day {
    font-size: 13px;
  }
}
</style>
