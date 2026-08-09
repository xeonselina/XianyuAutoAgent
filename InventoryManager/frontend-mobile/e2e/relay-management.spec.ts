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
  successor_accessories: [
    { name: '三脚架', type: 'tripod', is_bundled: false },
    { name: '备用电池', type: 'battery', is_bundled: false },
  ],
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

async function mockRelayApi(
  page: Page,
  xianyuSync?: { attempted: boolean; success: boolean; message: string },
) {
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
            xianyu_sync: xianyuSync,
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

    await expect(page.getByText('接力工作台', { exact: true })).toBeVisible()
    await expect(page.getByText('鹿鹿')).toBeVisible()
    await expect(page.getByText('王先生')).toBeVisible()
    await expect(page.getByText('13800138000')).toBeVisible()
    await expect(page.getByText('星星')).toBeVisible()
    await expect(page.getByText('李女士')).toBeVisible()
    await expect(page.getByText('X300U', { exact: true })).toBeVisible()
    await expect(page.getByText(/400MM 镜头/)).toBeVisible()
    await expect(page.getByText(/手柄/)).toBeVisible()
    await expect(page.getByTestId('equipment-warning')).toContainText('镜头组合不一致')
    await expect(page.getByTestId('equipment-warning')).toContainText('后单附件更多（2 > 1）')
    await expect(page.getByText(/2026-08-06/)).toBeVisible()
    await expect(page.getByText(/2026-08-09/)).toBeVisible()
    await expect(page.getByText('SF1234567890')).toBeVisible()
    await expect(page.getByText(/运送中/)).toBeVisible()
    await expect(page.getByTestId('status-chip-pending')).toBeVisible()
    await expect(page.getByTestId('status-chip-shipped')).toBeVisible()

    expect(await page.getByText('杭州市西湖区文三路 1 号').count()).toBe(0)
    await page.getByTestId('relay-expand-details').click()
    await expect(page.getByTestId('relay-card-details')).toBeVisible()
    await expect(page.getByText('杭州市西湖区文三路 1 号')).toBeVisible()
    await expect(page.getByText('上海市浦东新区世纪大道 2 号')).toBeVisible()

    expect(api.listRequests).toHaveLength(1)
    const requestUrl = new URL(api.listRequests[0])
    expect(requestUrl.searchParams.get('statuses')).toBe('pending,notified,agreed,shipped')
    expect(requestUrl.searchParams.get('per_page')).toBe('50')
  })

  test('provides touch-first status chips, date presets and card actions', async ({ page }) => {
    const api = await mockRelayApi(page)
    await page.goto('/mobile/relay')

    const toolbarPosition = await page.locator('.mobile-toolbar').evaluate(element =>
      getComputedStyle(element).position,
    )
    expect(toolbarPosition).toBe('sticky')

    await page.getByTestId('status-chip-completed').click()
    await expect.poll(() => api.listRequests.length).toBe(2)
    const statusUrl = new URL(api.listRequests[1])
    expect(statusUrl.searchParams.get('statuses')).toContain('completed')

    await page.getByTestId('relay-date-filter').click()
    await page.getByTestId('range-next-15').click()
    await expect.poll(() => api.listRequests.length).toBe(3)

    const actionButtons = page.locator('[data-testid="relay-card-actions"] .van-button')
    await expect(actionButtons).toHaveCount(2)
    const actionHeights = await actionButtons.evaluateAll(
      buttons => buttons.map(button => button.getBoundingClientRect().height),
    )
    expect(actionHeights).toHaveLength(2)
    expect(actionHeights.every(height => height >= 44)).toBe(true)
  })

  test('requires a tracking number before saving shipped', async ({ page }) => {
    const api = await mockRelayApi(page, {
      attempted: true,
      success: true,
      message: 'ok',
    })
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
    await expect(page.getByText('接力状态已更新，已同步闲鱼')).toBeVisible()
    await expect.poll(() => api.listRequests.length).toBe(2)
  })

  test('warns when local shipping succeeds but xianyu reporting fails', async ({ page }) => {
    const api = await mockRelayApi(page, {
      attempted: true,
      success: false,
      message: '闲鱼接口繁忙',
    })
    await page.goto('/mobile/relay')

    await page.getByTestId('relay-maintain').click()
    await page.getByTestId('save-relay-status').click()

    await expect.poll(() => api.updateBodies.length).toBe(1)
    await expect(page.getByText('接力已标记已寄出，但闲鱼上报失败：闲鱼接口繁忙')).toBeVisible()
    await expect(page.getByTestId('save-relay-status')).toBeHidden()
    await expect.poll(() => api.listRequests.length).toBe(2)
  })

  test('refreshes current-page logistics and is reachable from the bottom tab', async ({ page }) => {
    const api = await mockRelayApi(page)
    await page.goto('/mobile/gantt')

    await page.getByRole('tab', { name: '接力' }).click()
    await expect(page).toHaveURL(/\/mobile\/relay$/)
    await page.getByTestId('relay-refresh-all').click()
    await expect.poll(api.batchRefreshes).toBe(1)
  })

  test('loads the next page when the selected range has more than 50 cases', async ({ page }) => {
    const requests: string[] = []
    const secondCase = {
      ...relayCase,
      case_id: 8,
      pair_key: '3:4',
      predecessor: { ...relayCase.predecessor, id: 3, buyer_id: '月月' },
      successor: { ...relayCase.successor, id: 4, buyer_id: '晨晨' },
    }
    await page.route('**/api/relay-cases**', async route => {
      const url = new URL(route.request().url())
      if (route.request().method() !== 'GET') {
        await route.fulfill({ status: 404, json: { success: false, message: 'unexpected request' } })
        return
      }
      requests.push(url.toString())
      const requestedPage = Number(url.searchParams.get('page') || '1')
      await route.fulfill({
        json: {
          success: true,
          data: {
            ...relayList,
            items: requestedPage === 1 ? [relayCase] : [secondCase],
            total: 51,
            page: requestedPage,
            pages: 2,
          },
        },
      })
    })

    await page.goto('/mobile/relay')
    await page.getByTestId('relay-load-more').click()

    await expect(page.getByText('晨晨')).toBeVisible()
    expect(requests).toHaveLength(2)
    expect(new URL(requests[1]).searchParams.get('page')).toBe('2')
  })

  test('shows the backend business message when status update is rejected', async ({ page }) => {
    await page.route('**/api/relay-cases**', async route => {
      const request = route.request()
      const url = new URL(request.url())
      if (request.method() === 'GET') {
        await route.fulfill({ json: { success: true, data: relayList } })
        return
      }
      if (request.method() === 'PUT' && url.pathname === '/api/relay-cases/1/2') {
        await route.fulfill({
          status: 409,
          json: { success: false, message: '档期已变化，当前组合不再满足接力条件' },
        })
        return
      }
      await route.fulfill({ status: 404, json: { success: false, message: 'unexpected request' } })
    })

    await page.goto('/mobile/relay')
    await page.getByTestId('relay-maintain').click()
    await page.getByTestId('relay-status-completed').click()
    await page.getByTestId('save-relay-status').click()

    await expect(page.getByRole('alert')).toContainText('档期已变化，当前组合不再满足接力条件')
  })

  test('splits batch tracking refreshes at the backend limit of 100 cases', async ({ page }) => {
    const batchBodies: number[][] = []
    const manyCases = Array.from({ length: 101 }, (_, index) => ({
      ...relayCase,
      case_id: index + 1,
      pair_key: `${index + 1}:${index + 102}`,
      predecessor: { ...relayCase.predecessor, id: index + 1 },
      successor: { ...relayCase.successor, id: index + 102 },
    }))
    await page.route('**/api/relay-cases**', async route => {
      const request = route.request()
      const url = new URL(request.url())
      if (request.method() === 'GET') {
        await route.fulfill({
          json: {
            success: true,
            data: { ...relayList, items: manyCases, total: 101, pages: 1 },
          },
        })
        return
      }
      if (request.method() === 'POST' && url.pathname === '/api/relay-cases/tracking/refresh-batch') {
        const caseIds = request.postDataJSON().case_ids as number[]
        batchBodies.push(caseIds)
        await route.fulfill({
          json: {
            success: true,
            data: { items: [], total: caseIds.length, success_count: caseIds.length },
          },
        })
        return
      }
      await route.fulfill({ status: 404, json: { success: false, message: 'unexpected request' } })
    })

    await page.goto('/mobile/relay')
    await page.getByTestId('relay-refresh-all').click()

    await expect.poll(() => batchBodies.length).toBe(2)
    expect(batchBodies.map(ids => ids.length)).toEqual([100, 1])
  })
})
