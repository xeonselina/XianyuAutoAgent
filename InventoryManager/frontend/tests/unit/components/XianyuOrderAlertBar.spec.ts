import { mount } from '@vue/test-utils'
import { ElMessageBox } from 'element-plus'
import { afterEach, describe, expect, it, vi } from 'vitest'

import XianyuOrderAlertBar from '@/components/XianyuOrderAlertBar.vue'
import type { XianyuOrderAlertSnapshot } from '@/types/xianyuOrderAlert'


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


describe('XianyuOrderAlertBar', () => {
  afterEach(() => {
    vi.restoreAllMocks()
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
    expect(wrapper.text()).toContain('未录单检查失败')
    expect(wrapper.text()).toContain('请求超时')
  })

  it('shows a stale worker warning and allows an immediate check', async () => {
    const stale = makeSnapshot()
    stale.alerts = []
    stale.count = 0
    stale.sync.is_stale = true

    const wrapper = mountBar(stale)

    expect(wrapper.text()).toContain('未录单检查长时间未更新')
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
