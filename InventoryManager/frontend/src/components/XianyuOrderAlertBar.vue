<template>
  <section
    v-for="group in rentalAlertGroups"
    :key="group.kind"
    class="xianyu-alert-bar"
    :class="{ 'refund-review-bar': group.kind === 'refund_review' }"
    :data-testid="`xianyu-rental-alert-bar-${group.kind}`"
  >
    <div class="alert-summary">
      <div class="alert-copy">
        <strong>{{ group.headline }}</strong>
        <span v-if="statusText" class="sync-status">{{ statusText }}</span>
      </div>
      <el-button :data-testid="`toggle-${group.kind}`" @click="rentalExpanded[group.kind] = !rentalExpanded[group.kind]">
        {{ rentalExpanded[group.kind] ? '收起详情' : '展开详情' }}
      </el-button>
    </div>
    <div v-if="rentalExpanded[group.kind]" class="alert-list">
      <div v-for="alert in group.alerts" :key="`${alert.xianyu_shop_id}:${alert.order_no}`" class="rental-alert-order">
        <div class="order-main">
          <span>{{ alert.xianyu_shop_name }}</span>
          <strong>{{ alert.status_text }}</strong>
          <span>订单号：{{ alert.order_no }}</span>
          <span class="sync-status">核对时间：{{ formatTime(alert.last_seen_at) }}</span>
        </div>
        <div class="order-actions">
          <el-button
            :data-testid="`rental-ignore-${alert.order_no}`"
            @click="confirmRentalIgnore(alert)"
          >
            忽略提醒
          </el-button>
        </div>
        <p v-if="group.kind === 'refund_review'" class="rental-guidance">订单尚未关闭，请核对实际退款范围和仍需履约的设备。</p>
        <div v-for="rental in alert.rentals" :key="rental.id" class="rental-alert-row">
          <div class="alert-copy">
            <div class="order-main">
              <span class="buyer">{{ rental.customer_name }}</span>
              <span>{{ rental.device_name }}{{ rental.parent_rental_id ? '（关联附件）' : '' }}</span>
              <span>{{ rental.warehouse_name }}</span>
              <span>{{ rentalStatusText[rental.status] }}</span>
            </div>
            <span>档期：{{ rental.start_date }} 至 {{ rental.end_date }}</span>
            <span v-if="rental.status === 'shipped'" class="rental-guidance">已发货，请先核对退货及设备回收情况。</span>
          </div>
          <el-button
            :type="group.kind === 'closed' && rental.status !== 'shipped' ? 'danger' : 'primary'"
            :disabled="loading || busyRentalId !== undefined"
            :data-testid="`rental-action-${rental.id}`"
            @click="emit('rental-action', {
              orderNo: alert.order_no, shopId: alert.xianyu_shop_id, rentalId: rental.id,
              action: group.kind === 'closed' && rental.status !== 'shipped' ? 'delete' : 'review',
            })"
          >
            {{ group.kind === 'closed' && rental.status !== 'shipped' ? '删除档期' : '查看档期' }}
          </el-button>
        </div>
      </div>
    </div>
  </section>
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
          data-testid="refresh-alerts"
          :loading="loading"
          @click="$emit('refresh')"
        >
          立即检查
        </el-button>
        <el-button
          v-if="snapshot.count > 0"
          data-testid="toggle-alerts"
          @click="expanded = !expanded"
        >
          {{ expanded ? '收起详情' : '展开详情' }}
        </el-button>
      </div>
    </div>

    <div v-if="expanded && snapshot.count > 0" class="alert-list">
      <div
        v-for="alert in snapshot.alerts"
        :key="`${alert.xianyu_shop_id}:${alert.order_no}`"
        class="alert-order"
      >
        <div class="order-main">
          <span class="buyer">{{ alert.buyer_nick || '未知买家' }}</span>
          <span>{{ alert.xianyu_shop_name }}</span>
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
            @click="$emit('book', { orderNo: alert.order_no, shopId: alert.xianyu_shop_id, shopName: alert.xianyu_shop_name || '' })"
          >
            去补录
          </el-button>
          <el-button
            :data-testid="`ignore-${alert.order_no}`"
            @click="confirmIgnore(alert)"
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
  XianyuRentalAlert,
  XianyuRentalAlertAction,
} from '@/types/xianyuOrderAlert'


const props = defineProps<{
  snapshot: XianyuOrderAlertSnapshot
  loading: boolean
  busyRentalId?: number
}>()

const emit = defineEmits<{
  book: [payload: { orderNo: string; shopId: number; shopName: string }]
  ignore: [payload: { shopId: number; orderNo: string; reason: string }]
  refresh: []
  'rental-action': [payload: XianyuRentalAlertAction]
  'rental-ignore': [payload: { shopId: number; orderNo: string; reason: string }]
}>()

const expanded = ref(false)
const rentalExpanded = ref({ closed: false, refund_review: false })
const rentalStatusText = { not_shipped: '未发货', scheduled_for_shipping: '预约发货', shipped: '已发货' }
const rentalAlertGroups = computed(() => (['closed', 'refund_review'] as const).map(kind => {
  const alerts = (props.snapshot.rental_alerts || []).filter(alert => alert.kind === kind)
  return {
    kind, alerts,
    headline: kind === 'closed'
      ? `发现 ${alerts.length} 笔闲鱼订单已退款或关闭，但仍保留在档期管理中，请及时删除，避免误发货`
      : `发现 ${alerts.length} 笔档期订单存在退款或退货情况，请核对`,
  }
}).filter(group => group.alerts.length > 0))

const syncNeedsAttention = computed(() => (
  Boolean(props.snapshot.sync.last_error)
  || props.snapshot.sync.is_stale === true
))

const visible = computed(() => (
  props.snapshot.count > 0 || syncNeedsAttention.value
))

const headline = computed(() => {
  if (props.snapshot.count === 0) {
    return props.snapshot.sync.last_error
      ? '闲鱼订单检查失败'
      : '闲鱼订单检查长时间未更新'
  }
  return `发现 ${props.snapshot.count} 笔闲鱼订单尚未录入库存管理`
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
  if (sync.is_stale) {
    return sync.last_success_at
      ? `最近成功：${formatTime(sync.last_success_at)}；请立即检查`
      : '尚无成功检查记录；请立即检查'
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

const confirmIgnore = async (alert: XianyuOrderAlert) => {
  const orderNo = alert.order_no
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
    emit('ignore', { shopId: alert.xianyu_shop_id, orderNo, reason })
  } catch {
    // 用户取消时保持当前告警。
  }
}

const confirmRentalIgnore = async (alert: XianyuRentalAlert) => {
  try {
    const promptResult = await ElMessageBox.prompt(
      '请填写忽略这笔退款/关闭档期提醒的原因；档期不会被删除。',
      '忽略档期提醒',
      {
        confirmButtonText: '下一步',
        cancelButtonText: '取消',
        inputPlaceholder: '例如：买家线下已确认，继续保留档期',
        inputValidator: (value: string) => {
          const reason = value?.trim()
          if (!reason) return '忽略原因不能为空'
          if (reason.length > 500) return '忽略原因不能超过500个字符'
          return true
        },
      },
    )
    const reason = String(promptResult.value || '').trim()

    await ElMessageBox.confirm(
      `订单 ${alert.order_no} 的提醒将被永久忽略，档期仍会保留。是否继续？`,
      '确认忽略档期提醒',
      {
        type: 'warning',
        confirmButtonText: '永久忽略',
        cancelButtonText: '取消',
      },
    )
    emit('rental-ignore', {
      shopId: alert.xianyu_shop_id,
      orderNo: alert.order_no,
      reason,
    })
  } catch {
    // 用户取消输入或确认时不做任何操作。
  }
}
</script>

<style scoped>
.xianyu-alert-bar {
  flex: 0 0 auto;
  margin: 0 16px 12px;
  padding: 12px 16px;
  color: #7a271a;
  background: #fef0f0;
  border: 1px solid #fab6b6;
  border-radius: 6px;
}

.refund-review-bar {
  background: #fdf6ec;
  border-color: #f3d19e;
  color: #8a570d;
}

.rental-alert-order {
  padding: 12px;
  background: #fff;
  border-radius: 4px;
  overflow-wrap: anywhere;
}

.rental-alert-order .order-main {
  flex-wrap: wrap;
  row-gap: 4px;
}

.rental-alert-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid #ebeef5;
  font-size: 13px;
}

.rental-guidance {
  margin: 6px 0 0;
  font-size: 13px;
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
