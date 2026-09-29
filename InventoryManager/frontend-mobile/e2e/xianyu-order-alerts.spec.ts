import { expect, test, type Page } from '@playwright/test'
import { mockAuthenticatedMobileSession } from './helpers/mock-auth'

const rental = {
  id: 11, device_id: 8, warehouse_id: 1,
  device: { id: 8, name: '相机 8', serial_number: 'SN8', model: 'x300u' },
  xianyu_order_no: 'CLOSED-1', xianyu_shop_id: 7,
  customer_name: '张三', customer_phone: '13800138000', destination: '广州',
  start_date: '2026-09-28', end_date: '2026-10-01', status: 'not_shipped',
  includes_handle: false, includes_lens_mount: false, photo_transfer: false,
}

const snapshot = (closed = true, missing = true) => ({
  alerts: missing ? [{
    order_no: 'MISSING-1', xianyu_shop_id: 7, xianyu_shop_name: '测试店',
    pay_amount: 19900, buyer_nick: '买家甲', goods_title: '相机租赁',
  }] : [],
  rental_alerts: [...(closed ? [{
    order_no: 'CLOSED-1', xianyu_shop_id: 7, xianyu_shop_name: '测试店',
    kind: 'closed', status_text: '已关闭', last_seen_at: '2026-09-28T08:00:00',
    rentals: [
      { id: 11, customer_name: '张三', device_name: '相机 8', warehouse_id: 1,
        warehouse_name: '移动端 E2E 仓库', start_date: '2026-09-28', end_date: '2026-10-01', status: 'not_shipped' },
      { id: 12, customer_name: '李四', device_name: '相机 9', warehouse_id: 1,
        warehouse_name: '移动端 E2E 仓库', start_date: '2026-09-28', end_date: '2026-10-01', status: 'shipped' },
    ],
  }] : []), {
    order_no: 'REVIEW-1', xianyu_shop_id: 7, xianyu_shop_name: '测试店',
    kind: 'refund_review', status_text: '部分退款', last_seen_at: '2026-09-28T09:00:00',
    rentals: [{ id: 13, customer_name: '王五', device_name: '相机 13', warehouse_id: 1,
      warehouse_name: '移动端 E2E 仓库', start_date: '2026-09-28', end_date: '2026-10-01', status: 'not_shipped' }],
  }],
  count: missing ? 1 : 0, refreshing: false,
  sync: { last_success_at: '2026-09-28T08:00:00', last_error: null, is_stale: false },
  shops: [{ id: 7, name: '测试店' }],
})

const setup = async (page: Page, staleIdentity = false, withPendingReturn = false) => {
  let deleted = false
  let deleteCount = 0
  let ignoredMissing = false
  let ignoreCount = 0
  let returned = false
  await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
    const url = new URL(route.request().url())
    if (url.pathname === '/api/xianyu-order-alerts') {
      await route.fulfill({ json: { success: true, data: snapshot(!deleted, !ignoredMissing) } })
    } else if (url.pathname === '/api/xianyu-order-alerts/7/MISSING-1/ignore') {
      ignoreCount += 1
      ignoredMissing = true
      await route.fulfill({ json: { success: true, data: snapshot(!deleted, false) } })
    } else if (url.pathname === '/api/gantt/data') {
      await route.fulfill({ json: { success: true, data: { devices: [], rentals: deleted ? [] : [rental] } } })
    } else if (url.pathname === '/api/gantt/daily-stats') {
      await route.fulfill({ json: { success: true, data: { stats: {} } } })
    } else if (url.pathname === '/api/rentals/pending-returns') {
      await route.fulfill({ json: { success: true, data: { rentals: withPendingReturn && !returned ? [{
        id: 44, device_name: '现场相机', customer_name: '赵六', due_date: '2026-09-29',
        overdue_days: 0, fulfillment_mode: 'onsite',
      }] : [] } } })
    } else if (url.pathname === '/api/rentals/44/status' && route.request().method() === 'PUT') {
      returned = true
      await route.fulfill({ json: { success: true } })
    } else if (url.pathname === '/api/rentals/11') {
      await route.fulfill({ json: { success: true, data: staleIdentity ? { ...rental, xianyu_order_no: 'OTHER' } : rental } })
    } else if (url.pathname === '/api/rentals/fetch-xianyu-order') {
      await route.fulfill({ json: { success: true, data: {
        buyer_nick: '买家甲', receiver_mobile: '13800138000', pay_amount: 19900,
      } } })
    } else if (url.pathname === '/api/device-models') {
      await route.fulfill({ json: { success: true, data: [] } })
    } else if (url.pathname === '/api/devices') {
      await route.fulfill({ json: { devices: [] } })
    } else {
      await route.fulfill({ status: 500, json: { success: false, error: `Unexpected ${url.pathname}` } })
    }
  })
  await page.route('**/web/rentals/11', async route => {
    if (route.request().method() === 'DELETE') {
      deleteCount += 1
      deleted = true
      await route.fulfill({ json: { success: true } })
    } else {
      await route.fulfill({ status: 405 })
    }
  })
  await mockAuthenticatedMobileSession(page)
  await page.goto('/mobile/gantt')
  return {
    deletedCount: () => deleteCount,
    ignoredCount: () => ignoreCount,
    resolveMissing: () => { ignoredMissing = true },
  }
}

test('shows warnings and carries a missing order into booking', async ({ page }) => {
  await setup(page)
  await expect(page.getByTestId('mobile-rental-alert-closed')).toContainText('已退款或关闭')
  await expect(page.getByTestId('mobile-order-alert')).toContainText('尚未录入库存管理')
  await expect(page.getByTestId('mobile-rental-alert-refund_review')).toContainText('退款或退货')
  await page.getByTestId('mobile-rental-alert-closed').getByText('展开详情').click()
  await expect(page.getByTestId('mobile-rental-action-11')).toHaveText('删除档期')
  await expect(page.getByTestId('mobile-rental-action-12')).toHaveText('查看档期')
  await page.getByTestId('mobile-rental-alert-refund_review').getByText('展开详情').click()
  await expect(page.getByTestId('mobile-rental-action-13')).toHaveText('查看档期')
  await page.getByTestId('mobile-order-alert').getByText('展开详情').click()
  await page.getByTestId('mobile-order-alert').getByText('去补录').click()
  await expect(page).toHaveURL(/\/mobile\/create-rental\?/)
  await expect(page.locator('input[placeholder="选填，可自动填充客户信息"]')).toHaveValue('MISSING-1')
  await expect(page.locator('select[aria-label="闲鱼店铺"]')).toHaveValue('7')
})

test('confirms deletion and refreshes the closed-order warning', async ({ page }) => {
  const state = await setup(page)
  await page.getByTestId('mobile-rental-alert-closed').getByText('展开详情').click()
  await page.getByTestId('mobile-rental-action-11').click()
  await expect(page.getByText(/关联附件档期也会一并删除/)).toBeVisible()
  expect(state.deletedCount()).toBe(0)
  await page.getByRole('button', { name: '确定删除' }).click()
  await expect(page.getByTestId('mobile-rental-alert-closed')).toHaveCount(0)
  expect(state.deletedCount()).toBe(1)
})

test('requires a reason and confirmation before permanently ignoring a missing order', async ({ page }) => {
  const state = await setup(page)
  await page.getByTestId('mobile-order-alert').getByText('展开详情').click()
  await page.getByText('无需录入').click()
  await page.getByText('下一步').click()
  expect(state.ignoredCount()).toBe(0)
  await page.locator('.ignore-panel textarea').fill('非租赁商品')
  await page.getByText('下一步').click()
  await expect(page.getByText(/将被永久忽略且无法恢复/)).toBeVisible()
  expect(state.ignoredCount()).toBe(0)
  await page.getByRole('button', { name: '永久忽略' }).click()
  await expect(page.getByTestId('mobile-order-alert')).toHaveCount(0)
  expect(state.ignoredCount()).toBe(1)
})

test('does not delete when the rental no longer matches the alerted order', async ({ page }) => {
  const state = await setup(page, true)
  await page.getByTestId('mobile-rental-alert-closed').getByText('展开详情').click()
  await page.getByTestId('mobile-rental-action-11').click()
  await expect(page.getByText('档期已变更或不存在，请刷新提醒后重试')).toBeVisible()
  expect(state.deletedCount()).toBe(0)
  await expect(page.getByRole('button', { name: '确定删除' })).toHaveCount(0)
})

test('reloads missing-order warnings when returning from the booking form', async ({ page }) => {
  const state = await setup(page)
  await page.getByTestId('mobile-order-alert').getByText('展开详情').click()
  await page.getByText('去补录').click()
  await expect(page).toHaveURL(/\/mobile\/create-rental\?/)
  state.resolveMissing()
  await page.goBack()
  await expect(page).toHaveURL(/\/mobile\/gantt$/)
  await expect(page.getByTestId('mobile-order-alert')).toHaveCount(0)
})

test('keeps onsite pending returns and Xianyu warnings usable together', async ({ page }) => {
  await setup(page, false, true)
  await expect(page.getByTestId('mobile-rental-alert-closed')).toBeVisible()
  await page.getByText('待归还 1').click()
  await expect(page.getByText('现场相机 · 赵六')).toBeVisible()
  await page.getByRole('button', { name: '已归还' }).click()
  await page.getByRole('button', { name: '确认' }).click()
  await expect(page.getByText('待归还 1')).toHaveCount(0)
  await expect(page.getByTestId('mobile-rental-alert-closed')).toBeVisible()
})
