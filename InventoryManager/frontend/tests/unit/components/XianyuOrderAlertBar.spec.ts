import { mount } from '@vue/test-utils'
import { ElMessageBox } from 'element-plus'
import { afterEach, describe, expect, it, vi } from 'vitest'

import XianyuOrderAlertBar from '@/components/XianyuOrderAlertBar.vue'
import type { XianyuOrderAlertSnapshot, XianyuRentalAlert } from '@/types/xianyuOrderAlert'


const makeSnapshot = (
  orderNo = 'XY-1',
): XianyuOrderAlertSnapshot => ({
  alerts: [
    {
      order_no: orderNo,
      xianyu_shop_id: 7,
      xianyu_shop_name: '深圳店',
      pay_amount: 5001,
      buyer_nick: '测试买家',
      receiver_mobile: '13800138000',
      goods_title: '相机租赁',
      goods_sku_text: '套餐A',
      order_time: '2026-07-24T10:00:00',
    },
  ],
  count: 1,
  refreshing: false,
  sync: {
    last_attempt_at: '2026-07-24T10:01:00',
    last_success_at: '2026-07-24T10:01:00',
    last_error: null,
    is_stale: false,
    stale_after_seconds: 600,
  },
})

const mountBar = (snapshot: XianyuOrderAlertSnapshot) =>
  mount(XianyuOrderAlertBar, {
    props: { snapshot, loading: false },
    global: {
      stubs: {
        ElButton: {
          emits: ['click'],
          template: '<button @click="$emit(\'click\')"><slot /></button>',
        },
      },
    },
  })

const rentalAlert = (kind: XianyuRentalAlert['kind'] = 'closed'): XianyuRentalAlert => ({
  order_no: 'XY-2', xianyu_shop_id: 7, xianyu_shop_name: '深圳店', kind,
  status_text: kind === 'closed' ? '交易关闭' : '部分退款，请核对',
  last_seen_at: '2026-09-07T02:00:00Z',
  rentals: [10, 11].map(id => ({
    id, customer_name: '两台设备买家', device_name: `相机${id}`, warehouse_id: 1,
    warehouse_name: '深圳仓', start_date: '2026-09-09', end_date: '2026-09-12', status: 'not_shipped',
  })),
})

describe('XianyuOrderAlertBar', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('groups two rentals under one closed order and offers individual actions after expansion', async () => {
    const snapshot = makeSnapshot()
    snapshot.rental_alerts = [rentalAlert()]
    const wrapper = mountBar(snapshot)
    expect(wrapper.text()).toContain('发现 1 笔闲鱼订单已退款或关闭')
    expect(wrapper.find('[data-testid="rental-action-10"]').exists()).toBe(false)
    await wrapper.get('[data-testid="toggle-closed"]').trigger('click')
    expect(wrapper.text()).toContain('相机10')
    expect(wrapper.text()).toContain('相机11')
    expect(wrapper.text()).toContain('深圳仓')
    expect(wrapper.text()).toContain('2026-09-09 至 2026-09-12')
    await wrapper.get('[data-testid="rental-action-10"]').trigger('click')
    expect(wrapper.emitted('rental-action')).toEqual([[{
      orderNo: 'XY-2', shopId: 7, rentalId: 10, action: 'delete',
    }]])
    expect(wrapper.emitted('ignore')).toBeUndefined()
  })

  it('requires a reason and confirmation before ignoring a rental alert order', async () => {
    vi.spyOn(ElMessageBox, 'prompt').mockResolvedValue({
      value: '买家已线下确认，故意保留档期',
      action: 'confirm',
    })
    vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue('confirm')
    const snapshot = makeSnapshot()
    snapshot.rental_alerts = [rentalAlert()]
    const wrapper = mountBar(snapshot)

    await wrapper.get('[data-testid="toggle-closed"]').trigger('click')
    await wrapper.get('[data-testid="rental-ignore-XY-2"]').trigger('click')

    expect(ElMessageBox.confirm).toHaveBeenCalledWith(
      expect.stringContaining('档期仍会保留'),
      '确认忽略档期提醒',
      expect.objectContaining({ type: 'warning' }),
    )
    expect(wrapper.emitted('rental-ignore')).toEqual([
      [{ shopId: 7, orderNo: 'XY-2', reason: '买家已线下确认，故意保留档期' }],
    ])
  })

  it('asks for review rather than deletion on partial refunds and shipped rentals', async () => {
    const snapshot = makeSnapshot()
    snapshot.rental_alerts = [rentalAlert('refund_review')]
    const wrapper = mountBar(snapshot)
    await wrapper.get('[data-testid="toggle-refund_review"]').trigger('click')
    expect(wrapper.text()).toContain('部分退款，请核对')
    expect(wrapper.text()).not.toContain('删除档期')
    await wrapper.get('[data-testid="rental-action-10"]').trigger('click')
    expect(wrapper.emitted('rental-action')?.[0]).toEqual([{
      orderNo: 'XY-2', shopId: 7, rentalId: 10, action: 'review',
    }])

    const closed = rentalAlert()
    closed.rentals[0].status = 'shipped'
    await wrapper.setProps({ snapshot: { ...snapshot, rental_alerts: [closed] } })
    await wrapper.get('[data-testid="toggle-closed"]').trigger('click')
    expect(wrapper.text()).toContain('已发货，请先核对退货及设备回收情况')
    expect(wrapper.get('[data-testid="rental-action-10"]').text()).toBe('查看档期')
    expect(wrapper.get('[data-testid="rental-action-11"]').text()).toBe('删除档期')
  })

  it('removes handled rentals immediately and hides the bar once all are handled', async () => {
    const alert = rentalAlert()
    const snapshot = { ...makeSnapshot(), rental_alerts: [alert] }
    const wrapper = mountBar(snapshot)
    await wrapper.get('[data-testid="toggle-closed"]').trigger('click')
    await wrapper.setProps({ snapshot: { ...snapshot, rental_alerts: [{ ...alert, rentals: [alert.rentals[1]] }] } })
    expect(wrapper.find('[data-testid="rental-action-10"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="rental-action-11"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('发现 1 笔闲鱼订单已退款或关闭')
    await wrapper.setProps({ snapshot: { ...snapshot, rental_alerts: [] } })
    expect(wrapper.find('[data-testid="xianyu-rental-alert-bar-closed"]').exists()).toBe(false)
  })

  it('retains closed order details alongside failure and last successful time', async () => {
    const snapshot = makeSnapshot()
    snapshot.rental_alerts = [rentalAlert()]
    snapshot.sync.last_error = '1 笔档期订单状态查询失败，已保留原提醒'
    const wrapper = mountBar(snapshot)
    expect(wrapper.text()).toContain('已保留原提醒')
    expect(wrapper.text()).toContain('上次成功')
    await wrapper.get('[data-testid="toggle-closed"]').trigger('click')
    expect(wrapper.text()).toContain('相机10')
  })

  it('shows the count and emits the selected order for booking', async () => {
    const wrapper = mountBar(makeSnapshot())

    expect(wrapper.text()).toContain(
      '发现 1 笔闲鱼订单尚未录入库存管理',
    )
    await wrapper.get('[data-testid="toggle-alerts"]').trigger('click')

    expect(wrapper.text()).toContain('测试买家')
    expect(wrapper.text()).toContain('13800138000')
    expect(wrapper.text()).toContain('¥50.01')

    await wrapper.get('[data-testid="book-XY-1"]').trigger('click')
    expect(wrapper.emitted('book')).toEqual([[{
      orderNo: 'XY-1', shopId: 7, shopName: '深圳店',
    }]])
  })

  it('renders nothing after a successful check with no alerts', () => {
    const empty = makeSnapshot()
    empty.alerts = []
    empty.count = 0

    expect(
      mountBar(empty).find('[data-testid="xianyu-order-alert-bar"]').exists(),
    ).toBe(false)
  })

  it('shows sync failures even when no orders are cached', () => {
    const failed = makeSnapshot()
    failed.alerts = []
    failed.count = 0
    failed.sync.last_success_at = null
    failed.sync.last_error = '请求超时'

    const wrapper = mountBar(failed)

    expect(wrapper.find('[data-testid="xianyu-order-alert-bar"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('闲鱼订单检查失败')
    expect(wrapper.text()).toContain('请求超时')
  })

  it('shows a stale worker warning and allows an immediate check', async () => {
    const stale = makeSnapshot()
    stale.alerts = []
    stale.count = 0
    stale.sync.is_stale = true

    const wrapper = mountBar(stale)

    expect(wrapper.text()).toContain('闲鱼订单检查长时间未更新')
    await wrapper.get('[data-testid="refresh-alerts"]').trigger('click')
    expect(wrapper.emitted('refresh')).toEqual([[]])
  })

  it('requires a reason and confirmation before emitting permanent ignore', async () => {
    vi.spyOn(ElMessageBox, 'prompt').mockResolvedValue({
      value: '非租赁商品',
      action: 'confirm',
    })
    vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue('confirm')
    const wrapper = mountBar(makeSnapshot())

    await wrapper.get('[data-testid="toggle-alerts"]').trigger('click')
    await wrapper.get('[data-testid="ignore-XY-1"]').trigger('click')

    expect(ElMessageBox.confirm).toHaveBeenCalledWith(
      expect.stringContaining('永久忽略且无法恢复'),
      '确认永久忽略',
      expect.objectContaining({ type: 'warning' }),
    )
    expect(wrapper.emitted('ignore')).toEqual([
      [{ shopId: 7, orderNo: 'XY-1', reason: '非租赁商品' }],
    ])
  })

  it('rejects ignore reasons longer than 500 characters', async () => {
    const prompt = vi.spyOn(ElMessageBox, 'prompt').mockResolvedValue({
      value: '非租赁商品',
      action: 'confirm',
    })
    const wrapper = mountBar(makeSnapshot())

    await wrapper.get('[data-testid="toggle-alerts"]').trigger('click')
    await wrapper.get('[data-testid="ignore-XY-1"]').trigger('click')

    const options = prompt.mock.calls[0][2]
    expect(options?.inputValidator?.('原'.repeat(501))).toBe(
      '忽略原因不能超过500个字符',
    )
  })
})
