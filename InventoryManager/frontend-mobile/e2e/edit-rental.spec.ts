import { test, expect } from '@playwright/test'
import { mockAuthenticatedMobileSession } from './helpers/mock-auth'

/**
 * Edit Rental spec
 *
 * Tests the "发货到闲鱼" (ship-to-xianyu) button visibility rules:
 *   - visible when rental.status === 'not_shipped'
 *   - hidden  for all other statuses
 *
 * Strategy: use the search API to find existing rentals by status,
 * then navigate to their edit pages (read-only lookup — no mutations).
 */

const BASE_URL = 'http://localhost:5003'

/** Fetch a rental ID for a given status by searching the API directly */
async function findRentalByStatus(status: string): Promise<number | null> {
  const resp = await fetch(`${BASE_URL}/api/rentals?page=1&per_page=100`)
  if (!resp.ok) return null
  const data = await resp.json()
  const rentals: any[] = data?.data?.rentals ?? data?.data?.items ?? data?.data ?? []
  const found = rentals.find((r: any) => r.status === status)
  return found ? found.id : null
}

test.describe('Edit Rental — ship-to-xianyu button', () => {
  test('ship-to-xianyu button is visible for not_shipped rental', async ({ page }) => {
    // Find a not_shipped rental via API
    const id = await findRentalByStatus('not_shipped')
    if (!id) {
      console.log('No not_shipped rental found in DB — skipping test')
      test.skip()
      return
    }

    await page.goto(`/mobile/edit-rental/${id}`)
    await page.waitForSelector('form, .edit-form, .van-form', { timeout: 8_000 })

    const shipBtn = page.locator('button:has-text("发货到闲鱼"), .van-button:has-text("发货到闲鱼")')
    await expect(shipBtn).toBeVisible()
  })

  test('ship-to-xianyu button is hidden for shipped rental', async ({ page }) => {
    const id = await findRentalByStatus('shipped')
    if (!id) {
      console.log('No shipped rental found in DB — skipping test')
      test.skip()
      return
    }

    await page.goto(`/mobile/edit-rental/${id}`)
    await page.waitForSelector('form, .edit-form, .van-form', { timeout: 8_000 })

    const shipBtn = page.locator('button:has-text("发货到闲鱼"), .van-button:has-text("发货到闲鱼")')
    await expect(shipBtn).not.toBeVisible()
  })

  test('ship-to-xianyu button is hidden for completed rental', async ({ page }) => {
    const id = await findRentalByStatus('completed')
    if (!id) {
      console.log('No completed rental found in DB — skipping test')
      test.skip()
      return
    }

    await page.goto(`/mobile/edit-rental/${id}`)
    await page.waitForSelector('form, .edit-form, .van-form', { timeout: 8_000 })

    const shipBtn = page.locator('button:has-text("发货到闲鱼"), .van-button:has-text("发货到闲鱼")')
    await expect(shipBtn).not.toBeVisible()
  })

  test('edit form loads and shows 保存修改 button', async ({ page }) => {
    // Generic smoke test — just needs any rental
    const resp = await page.request.get(`${BASE_URL}/api/rentals?page=1&per_page=5`)
    const data = await resp.json()
    const rentals: any[] = data?.data?.rentals ?? data?.data?.items ?? data?.data ?? []
    if (!rentals.length) {
      console.log('No rentals in DB — skipping')
      test.skip()
      return
    }

    const id = rentals[0].id
    await page.goto(`/mobile/edit-rental/${id}`)
    await page.waitForSelector('.van-button:has-text("保存修改")', { timeout: 8_000 })

    const saveBtn = page.locator('.van-button:has-text("保存修改")')
    await expect(saveBtn).toBeVisible()
  })
})

test.describe('Edit Rental — damage note', () => {
  test('loads and submits the current customer damage report', async ({ page }) => {
    await mockAuthenticatedMobileSession(page)

    const rental = {
      id: 77,
      device_id: 9,
      warehouse_id: 1,
      device: {
        id: 9,
        name: '2001',
        serial_number: 'SN-2001',
        model: 'x200u',
      },
      start_date: '2026-08-01',
      end_date: '2026-08-05',
      customer_name: '测试客户',
      customer_phone: '13800138000',
      destination: '测试地址',
      status: 'returned',
      includes_handle: false,
      includes_lens_mount: false,
      photo_transfer: false,
      accessories: [],
      damage_note: '屏幕右下角碎裂',
    }
    let updateBody: Record<string, unknown> | null = null

    await page.route('**/api/gantt/data**', route => route.fulfill({
      json: { success: true, data: { devices: [rental.device], rentals: [rental] } },
    }))
    await page.route('**/api/devices**', route => route.fulfill({
      json: { devices: [] },
    }))
    await page.route('**/api/rentals/77', route => route.fulfill({
      json: { success: true, data: rental },
    }))
    await page.route('**/web/rentals/77', async route => {
      updateBody = route.request().postDataJSON()
      await route.fulfill({ json: { success: true, data: { id: 77 } } })
    })

    await page.goto('/mobile/edit-rental/77')

    const damageField = page.getByTestId('damage-note').locator('textarea')
    await expect(damageField).toHaveValue('屏幕右下角碎裂')
    await expect(page.getByTestId('damage-note-warning')).toContainText('已记录用户损坏反馈')

    await damageField.fill('镜头卡口松动')
    await page.getByTestId('save-rental').click()

    await expect.poll(() => updateBody?.damage_note).toBe('镜头卡口松动')
  })
})
