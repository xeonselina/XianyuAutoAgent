import { expect, test, type Page } from '@playwright/test'

const relayCase = {
  case_id: 7,
  pair_key: '1:2',
  status: 'shipped',
  binding_id: 3,
  schedule_changed: false,
  overlap_days: 2,
  planned_ship_date: '2026-08-06',
  planned_receive_date: '2026-08-09',
  device: {
    id: 11,
    name: 'X300U-11',
    model: 'x300u',
    model_id: 4,
    model_display_name: 'X300U',
  },
  lens_combo: 'lens_400mm',
  accessories: [{ name: '手柄', type: 'handle', is_bundled: true }],
  successor_lens_combo: 'lens_200mm',
  successor_accessories: [{ name: '三脚架', type: 'tripod', is_bundled: false }],
  predecessor: {
    id: 1,
    start_date: '2026-08-01',
    end_date: '2026-08-05',
    buyer_id: '鹿鹿',
    customer_name: '王先生',
    customer_phone: '13800138000',
    destination: '杭州市西湖区文三路 1 号',
  },
  successor: {
    id: 2,
    start_date: '2026-08-10',
    end_date: '2026-08-14',
    buyer_id: '星星',
    customer_name: '李女士',
    customer_phone: '13900139000',
    destination: '上海市浦东新区世纪大道 2 号',
  },
  tracking: {
    number: 'SF1234567890',
    status: 'in_transit',
    summary: '运送中 · 2026-08-05 10:00:00',
    last_checked_at: '2026-08-05T10:01:00',
  },
  created_at: '2026-08-01T10:00:00',
  updated_at: '2026-08-05T10:01:00',
}

const relayList = {
  items: [relayCase],
  total: 1,
  page: 1,
  per_page: 50,
  pages: 1,
  open_total: 1,
  filters: {
    statuses: ['pending', 'notified', 'agreed', 'shipped'],
    ship_date_from: '2026-08-02',
    ship_date_to: '2026-08-10',
  },
}

async function mockRelayApi(page: Page) {
  const listRequests: string[] = []
  const updateBodies: unknown[] = []
  let batchRefreshes = 0

  await page.route('**/api/relay-cases**', async route => {
    const request = route.request()
    const url = new URL(request.url())

    if (request.method() === 'GET' && url.pathname === '/api/relay-cases') {
      listRequests.push(url.toString())
      await route.fulfill({ json: { success: true, data: relayList } })
      return
    }
    if (request.method() === 'PUT' && url.pathname === '/api/relay-cases/1/2') {
      updateBodies.push(request.postDataJSON())
      await route.fulfill({
        json: {
          success: true,
          data: {
            case_id: 7,
            predecessor_rental_id: 1,
            successor_rental_id: 2,
            status: 'shipped',
            sf_tracking_number: 'SF999',
            tracking: { number: 'SF999', status: 'unknown', summary: null, last_checked_at: null },
          },
        },
      })
      return
    }
    if (request.method() === 'POST' && url.pathname === '/api/relay-cases/tracking/refresh-batch') {
      batchRefreshes += 1
      await route.fulfill({
        json: { success: true, data: { items: [], total: 1, success_count: 1 } },
      })
      return
    }
    if (request.method() === 'POST' && url.pathname === '/api/relay-cases/7/tracking/refresh') {
      await route.fulfill({ json: { success: true, data: relayCase.tracking } })
      return
    }
    await route.fulfill({ status: 404, json: { success: false, message: 'unexpected request' } })
  })

  return { listRequests, updateBodies, batchRefreshes: () => batchRefreshes }
}

test.describe('mobile relay management', () => {
  test('uses open-status defaults and renders the complete relay card', async ({ page }) => {
    const api = await mockRelayApi(page)
    await page.goto('/mobile/relay')

    await expect(page.getByText('接力管理', { exact: true })).toBeVisible()
    await expect(page.getByText('鹿鹿')).toBeVisible()
    await expect(page.getByText('王先生')).toBeVisible()
    await expect(page.getByText('13800138000')).toBeVisible()
    await expect(page.getByText('星星')).toBeVisible()
    await expect(page.getByText('李女士')).toBeVisible()
    await expect(page.getByText('X300U', { exact: true })).toBeVisible()
    await expect(page.getByText(/400MM 镜头/)).toBeVisible()
    await expect(page.getByText(/手柄/)).toBeVisible()
    await expect(page.getByText(/2026-08-06/)).toBeVisible()
    await expect(page.getByText(/2026-08-09/)).toBeVisible()
    await expect(page.getByText('SF1234567890')).toBeVisible()
    await expect(page.getByText(/运送中/)).toBeVisible()

    expect(api.listRequests).toHaveLength(1)
    const requestUrl = new URL(api.listRequests[0])
    expect(requestUrl.searchParams.get('statuses')).toBe('pending,notified,agreed,shipped')
    expect(requestUrl.searchParams.get('per_page')).toBe('50')
  })

  test('requires a tracking number before saving shipped', async ({ page }) => {
    const api = await mockRelayApi(page)
    await page.goto('/mobile/relay')

    await page.getByTestId('relay-maintain').click()
    await page.getByTestId('relay-status-shipped').click()
    await page.getByTestId('relay-tracking-input').fill('')
    await page.getByTestId('save-relay-status').click()
    await expect(page.getByText('请输入顺丰运单号')).toBeVisible()
    expect(api.updateBodies).toHaveLength(0)

    await page.getByTestId('relay-tracking-input').fill('SF999')
    await page.getByTestId('save-relay-status').click()
    await expect.poll(() => api.updateBodies.length).toBe(1)
    expect(api.updateBodies[0]).toEqual({ status: 'shipped', sf_tracking_number: 'SF999' })
  })

  test('refreshes current-page logistics and is reachable from the bottom tab', async ({ page }) => {
    const api = await mockRelayApi(page)
    await page.goto('/mobile/gantt')

    await page.getByRole('tab', { name: '接力' }).click()
    await expect(page).toHaveURL(/\/mobile\/relay$/)
    await page.getByTestId('relay-refresh-all').click()
    await expect.poll(api.batchRefreshes).toBe(1)
  })
})
