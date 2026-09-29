<template>
  <div v-if="rentalGroups.length || showOrderAlert" class="alerts">
    <section
      v-for="group in rentalGroups"
      :key="group.kind"
      class="alert"
      :class="group.kind === 'closed' ? 'alert-danger' : 'alert-review'"
      :data-testid="`mobile-rental-alert-${group.kind}`"
    >
      <div class="heading">
        <strong>{{ group.headline }}</strong>
        <van-button size="mini" plain @click="expanded[group.kind] = !expanded[group.kind]">
          {{ expanded[group.kind] ? '收起详情' : '展开详情' }}
        </van-button>
      </div>
      <small v-if="statusText">{{ statusText }}</small>
      <div v-if="expanded[group.kind]" class="details">
        <article v-for="alert in group.alerts" :key="`${alert.xianyu_shop_id}:${alert.order_no}`" class="order">
          <div><strong>{{ alert.status_text }}</strong> · {{ alert.xianyu_shop_name }}</div>
          <div>订单号：{{ alert.order_no }}</div>
          <small>核对时间：{{ formatTime(alert.last_seen_at) }}</small>
          <p v-if="group.kind === 'refund_review'" class="guidance">订单尚未关闭，请核对实际退款范围和仍需履约的设备。</p>
          <div v-for="rental in alert.rentals" :key="rental.id" class="rental">
            <div>{{ rental.customer_name }} · {{ rental.device_name }}{{ rental.parent_rental_id ? '（关联附件）' : '' }}</div>
            <div>{{ rental.warehouse_name }} · {{ rentalStatusText[rental.status] }}</div>
            <div>档期：{{ rental.start_date }} 至 {{ rental.end_date }}</div>
            <p v-if="rental.status === 'shipped'" class="guidance">已发货，请先核对退货及设备回收情况。</p>
            <van-button
              size="small"
              :type="group.kind === 'closed' && rental.status !== 'shipped' ? 'danger' : 'primary'"
              :disabled="loading || busyRentalId !== undefined"
              :data-testid="`mobile-rental-action-${rental.id}`"
              @click="emit('rental-action', {
                orderNo: alert.order_no, shopId: alert.xianyu_shop_id, rentalId: rental.id,
                action: group.kind === 'closed' && rental.status !== 'shipped' ? 'delete' : 'review',
              })"
            >{{ group.kind === 'closed' && rental.status !== 'shipped' ? '删除档期' : '查看档期' }}</van-button>
          </div>
          <van-button size="small" plain :disabled="loading" @click="openIgnore('rental', alert)">忽略提醒</van-button>
        </article>
      </div>
    </section>

    <section v-if="showOrderAlert" class="alert alert-missing" data-testid="mobile-order-alert">
      <div class="heading">
        <strong>{{ orderHeadline }}</strong>
        <van-button v-if="snapshot.count" size="mini" plain @click="expanded.order = !expanded.order">
          {{ expanded.order ? '收起详情' : '展开详情' }}
        </van-button>
      </div>
      <small v-if="statusText">{{ statusText }}</small>
      <van-button size="small" plain :loading="loading" @click="emit('refresh')">立即检查</van-button>
      <div v-if="expanded.order && snapshot.count" class="details">
        <article v-for="alert in snapshot.alerts" :key="`${alert.xianyu_shop_id}:${alert.order_no}`" class="order">
          <div><strong>{{ alert.buyer_nick || '未知买家' }}</strong> · {{ alert.xianyu_shop_name }}</div>
          <div>{{ alert.receiver_mobile || '无手机号' }} · {{ formatAmount(alert.pay_amount) }}</div>
          <div>{{ [alert.goods_title, alert.goods_sku_text].filter(Boolean).join(' · ') || '未提供商品信息' }}</div>
          <div>订单号：{{ alert.order_no }}</div>
          <small>{{ formatTime(alert.order_time) }}</small>
          <div class="actions">
            <van-button size="small" type="primary" @click="emit('book', { orderNo: alert.order_no, shopId: alert.xianyu_shop_id })">
              {{ alert.expected_quantity ? '去补齐' : '去补录' }}
            </van-button>
            <van-button v-if="!alert.expected_quantity" size="small" plain :disabled="loading" @click="openIgnore('order', alert)">无需录入</van-button>
          </div>
        </article>
      </div>
    </section>

    <van-popup v-model:show="ignoreVisible" position="bottom" round closeable>
      <div class="ignore-panel">
        <h3>{{ ignoreKind === 'order' ? '标记为无需录入' : '忽略档期提醒' }}</h3>
        <p>{{ ignoreKind === 'order' ? '请填写该订单无需录入库存管理的原因。' : '请填写忽略这笔退款/关闭档期提醒的原因；档期不会被删除。' }}</p>
        <van-field v-model="ignoreReason" type="textarea" rows="3" maxlength="500" show-word-limit placeholder="请输入原因" />
        <van-button block type="danger" @click="confirmIgnore">下一步</van-button>
      </div>
    </van-popup>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { showConfirmDialog, showToast } from 'vant'
import type { XianyuOrderAlert, XianyuOrderAlertSnapshot, XianyuRentalAlert, XianyuRentalAlertAction } from '@/types/xianyuOrderAlert'

const props = defineProps<{
  snapshot: XianyuOrderAlertSnapshot
  loading: boolean
  busyRentalId?: number
}>()
const emit = defineEmits<{
  book: [payload: { orderNo: string; shopId: number }]
  ignore: [payload: { shopId: number; orderNo: string; reason: string }]
  'rental-ignore': [payload: { shopId: number; orderNo: string; reason: string }]
  'rental-action': [payload: XianyuRentalAlertAction]
  refresh: []
}>()

const expanded = ref({ closed: false, refund_review: false, order: false })
const rentalStatusText = { not_shipped: '未发货', scheduled_for_shipping: '预约发货', shipped: '已发货' }
const rentalGroups = computed(() => (['closed', 'refund_review'] as const).map(kind => {
  const alerts = (props.snapshot.rental_alerts || []).filter(alert => alert.kind === kind)
  return {
    kind, alerts,
    headline: kind === 'closed'
      ? `发现 ${alerts.length} 笔闲鱼订单已退款或关闭，但仍保留在档期管理中，请及时删除，避免误发货`
      : `发现 ${alerts.length} 笔档期订单存在退款或退货情况，请核对`,
  }
}).filter(group => group.alerts.length > 0))
const showOrderAlert = computed(() => props.snapshot.count > 0 || !!props.snapshot.sync.last_error || !!props.snapshot.sync.is_stale)
const orderHeadline = computed(() => props.snapshot.count
  ? `发现 ${props.snapshot.count} 笔闲鱼订单尚未录入库存管理`
  : props.snapshot.sync.last_error ? '闲鱼订单检查失败' : '闲鱼订单检查长时间未更新')
const statusText = computed(() => {
  const sync = props.snapshot.sync
  if (sync.last_error) return `${sync.last_error}${sync.last_success_at ? `；上次成功：${formatTime(sync.last_success_at)}` : ''}`
  if (props.loading || props.snapshot.refreshing) return '正在刷新'
  if (sync.is_stale) return sync.last_success_at
    ? `最近成功：${formatTime(sync.last_success_at)}；请立即检查`
    : '尚无成功检查记录；请立即检查'
  return ''
})
const formatTime = (value?: string | null) => {
  if (!value) return '时间未知'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false })
}
const formatAmount = (cents: number) => `¥${(Number(cents || 0) / 100).toFixed(2)}`

const ignoreVisible = ref(false)
const ignoreReason = ref('')
const ignoreKind = ref<'order' | 'rental'>('order')
const ignoredAlert = ref<XianyuOrderAlert | XianyuRentalAlert | null>(null)
const openIgnore = (kind: 'order' | 'rental', alert: XianyuOrderAlert | XianyuRentalAlert) => {
  ignoreKind.value = kind
  ignoredAlert.value = alert
  ignoreReason.value = ''
  ignoreVisible.value = true
}
const confirmIgnore = async () => {
  const alert = ignoredAlert.value
  const reason = ignoreReason.value.trim()
  if (!alert) return
  if (!reason) { showToast('忽略原因不能为空'); return }
  if (reason.length > 500) { showToast('忽略原因不能超过500个字符'); return }
  try {
    await showConfirmDialog({
      title: ignoreKind.value === 'order' ? '确认永久忽略' : '确认忽略档期提醒',
      message: ignoreKind.value === 'order'
        ? `订单 ${alert.order_no} 将被永久忽略且无法恢复。是否继续？`
        : `订单 ${alert.order_no} 的提醒将被永久忽略，档期仍会保留。是否继续？`,
      confirmButtonText: '永久忽略',
      confirmButtonColor: '#ee0a24',
    })
  } catch { return }
  const payload = { shopId: alert.xianyu_shop_id, orderNo: alert.order_no, reason }
  if (ignoreKind.value === 'order') emit('ignore', payload)
  else emit('rental-ignore', payload)
  ignoreVisible.value = false
}
</script>

<style scoped>
.alerts { max-height: 36vh; overflow-y: auto; flex: none; padding: 6px 10px; background: #f7f8fa; }
.alert { border-left: 4px solid #ee0a24; background: #fff7f7; border-radius: 5px; padding: 10px; margin-bottom: 6px; font-size: 12px; line-height: 1.5; overflow-wrap: anywhere; }
.alert-review { border-color: #ff976a; background: #fff9ef; }
.alert-missing { border-color: #ff976a; background: #fffbe8; }
.heading { display: flex; align-items: flex-start; gap: 8px; justify-content: space-between; }
.heading strong { flex: 1; font-size: 13px; }
.heading .van-button { flex: none; }
small { display: block; color: #666; margin: 4px 0; }
.details { padding-top: 8px; }
.order { padding: 8px 0; border-top: 1px solid #e7d9d9; }
.order > div { margin-bottom: 3px; }
.rental { margin: 8px 0; padding: 8px; background: #fff; border-radius: 4px; }
.rental .van-button { margin-top: 6px; }
.guidance { margin: 4px 0; color: #b45f06; }
.actions { display: flex; gap: 8px; padding-top: 6px; }
.ignore-panel { padding: 20px 16px calc(20px + env(safe-area-inset-bottom)); }
.ignore-panel h3 { margin: 0 0 6px; }
.ignore-panel p { color: #666; font-size: 13px; }
.ignore-panel .van-button { margin-top: 16px; }
</style>
