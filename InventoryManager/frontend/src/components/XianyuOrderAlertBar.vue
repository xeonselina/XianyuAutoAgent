<template>
  <section
    v-if="visible"
    class="xianyu-alert-bar"
    data-testid="xianyu-order-alert-bar"
  >
    <div class="alert-summary">
      <div class="alert-copy">
        <strong>{{ headline }}</strong>
        <span v-if="statusText" class="sync-status">{{ statusText }}</span>
      </div>

      <div class="alert-actions">
        <el-button
          v-if="snapshot.count > 0"
          data-testid="toggle-alerts"
          @click="expanded = !expanded"
        >
          {{ expanded ? '收起详情' : '展开详情' }}
        </el-button>
        <el-button
          type="danger"
          plain
          :loading="loading || snapshot.refreshing"
          @click="$emit('refresh')"
        >
          刷新
        </el-button>
      </div>
    </div>

    <div v-if="expanded && snapshot.count > 0" class="alert-list">
      <div
        v-for="alert in snapshot.alerts"
        :key="alert.order_no"
        class="alert-order"
      >
        <div class="order-main">
          <span class="buyer">{{ alert.buyer_nick || '未知买家' }}</span>
          <span>{{ alert.receiver_mobile || '无手机号' }}</span>
          <span class="amount">{{ formatAmount(alert.pay_amount) }}</span>
          <span>{{ formatTime(alert.order_time) }}</span>
        </div>
        <div class="order-detail">
          <span>{{ goodsText(alert) }}</span>
          <span class="order-number">订单号：{{ alert.order_no }}</span>
        </div>
        <div class="order-actions">
          <el-button
            type="primary"
            :data-testid="`book-${alert.order_no}`"
            @click="$emit('book', alert.order_no)"
          >
            去补录
          </el-button>
          <el-button
            :data-testid="`ignore-${alert.order_no}`"
            @click="confirmIgnore(alert.order_no)"
          >
            无需录入
          </el-button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { ElMessageBox } from 'element-plus'

import type {
  XianyuOrderAlert,
  XianyuOrderAlertSnapshot,
} from '@/types/xianyuOrderAlert'


const props = defineProps<{
  snapshot: XianyuOrderAlertSnapshot
  loading: boolean
}>()

const emit = defineEmits<{
  refresh: []
  book: [orderNo: string]
  ignore: [payload: { orderNo: string; reason: string }]
}>()

const expanded = ref(false)

const visible = computed(() => (
  props.snapshot.count > 0
  || Boolean(props.snapshot.sync.last_error)
  || !props.snapshot.sync.last_success_at
))

const headline = computed(() => {
  if (props.snapshot.count > 0) {
    return `发现 ${props.snapshot.count} 笔待发货订单尚未录入库存管理`
  }
  if (props.snapshot.sync.last_error) {
    return '暂时无法检查漏录订单'
  }
  return '正在检查闲鱼漏录订单…'
})

const statusText = computed(() => {
  const sync = props.snapshot.sync
  if (sync.last_error) {
    const lastSuccess = sync.last_success_at
      ? `；上次成功：${formatTime(sync.last_success_at)}`
      : ''
    return `${sync.last_error}${lastSuccess}`
  }
  if (props.loading || props.snapshot.refreshing) {
    return '正在刷新'
  }
  return ''
})

const formatAmount = (cents: number) => (
  `¥${(Number(cents || 0) / 100).toFixed(2)}`
)

const formatTime = (value?: string | null) => {
  if (!value) return '时间未知'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('zh-CN', { hour12: false })
}

const goodsText = (alert: XianyuOrderAlert) => {
  const parts = [alert.goods_title, alert.goods_sku_text].filter(Boolean)
  return parts.length ? parts.join(' · ') : '未提供商品信息'
}

const confirmIgnore = async (orderNo: string) => {
  try {
    const promptResult = await ElMessageBox.prompt(
      '请填写该订单无需录入库存管理的原因',
      '标记为无需录入',
      {
        confirmButtonText: '下一步',
        cancelButtonText: '取消',
        inputPlaceholder: '例如：非租赁商品',
        inputValidator: (value: string) => {
          const reason = value?.trim()
          if (!reason) return '忽略原因不能为空'
          if (reason.length > 500) {
            return '忽略原因不能超过500个字符'
          }
          return true
        },
      },
    )
    const reason = String(promptResult.value || '').trim()

    await ElMessageBox.confirm(
      `订单 ${orderNo} 将被永久忽略且无法恢复。是否继续？`,
      '确认永久忽略',
      {
        type: 'warning',
        confirmButtonText: '永久忽略',
        cancelButtonText: '取消',
      },
    )
    emit('ignore', { orderNo, reason })
  } catch {
    // 用户取消时保持当前告警。
  }
}
</script>

<style scoped>
.xianyu-alert-bar {
  margin: 0 16px 12px;
  padding: 12px 16px;
  color: #7a271a;
  background: #fef0f0;
  border: 1px solid #fab6b6;
  border-radius: 6px;
}

.alert-summary,
.alert-actions,
.order-main,
.order-detail,
.order-actions {
  display: flex;
  align-items: center;
}

.alert-summary {
  justify-content: space-between;
  gap: 16px;
}

.alert-copy {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.sync-status {
  color: #a63d32;
  font-size: 12px;
}

.alert-actions,
.order-actions {
  gap: 8px;
  flex: 0 0 auto;
}

.alert-list {
  display: grid;
  gap: 8px;
  margin-top: 12px;
}

.alert-order {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 6px 16px;
  padding: 10px 12px;
  background: #fff;
  border-radius: 4px;
}

.order-main,
.order-detail {
  min-width: 0;
  gap: 16px;
}

.order-main {
  font-size: 14px;
}

.order-detail {
  grid-column: 1;
  color: #606266;
  font-size: 12px;
}

.order-actions {
  grid-column: 2;
  grid-row: 1 / span 2;
}

.buyer,
.amount {
  font-weight: 600;
}

.order-number {
  color: #909399;
}

@media (max-width: 900px) {
  .alert-summary,
  .alert-order,
  .order-main,
  .order-detail {
    align-items: flex-start;
    flex-direction: column;
  }

  .alert-order {
    display: flex;
  }
}
</style>
