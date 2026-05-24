import { test, expect } from '@playwright/test'

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
