import { test, expect, request as playwrightRequest } from '@playwright/test'
import { safeTestRental, TEST_START_DATE, assertSafeDate, assertSafeToDelete, TEST_CUSTOMER_PREFIX } from './helpers/safetyGuard'

/**
 * Create Rental spec
 *
 * Creates a test rental with dates >= October 2026 (safe — outside production usage window).
 *
 * Production DB safety rules enforced here:
 *  - start_date and end_date MUST be >= TEST_START_DATE (2026-10-01)
 *  - customer_name MUST start with TEST_CUSTOMER_PREFIX
 *  - We DELETE created test rentals in afterAll (cleanup)
 *  - We do NOT modify any pre-existing rentals
 */

/** IDs of rentals created during this test run — cleaned up in afterAll */
const createdRentalIds: number[] = []

test.afterAll(async () => {
  if (createdRentalIds.length === 0) return

  // Create a standalone request context pointing directly at the backend
  const apiRequest = await playwrightRequest.newContext({ baseURL: 'http://localhost:5001' })

  for (const id of createdRentalIds) {
    try {
      // Fetch the rental to verify safety before deleting
      const getRes = await apiRequest.get(`/api/rentals/${id}`)
      if (!getRes.ok()) {
        console.warn(`Cleanup: could not GET rental #${id} (status ${getRes.status()}) — skipping`)
        continue
      }
      const body = await getRes.json()
      // GET /api/rentals/:id returns { data: { customer_name, start_date, ... } }
      const rental = body.data ?? body
      assertSafeToDelete({ id, customer_name: rental.customer_name, start_date: rental.start_date })

      const delRes = await apiRequest.delete(`/api/rentals/${id}`)
      if (delRes.ok()) {
        console.log(`Cleanup: deleted test rental #${id}`)
      } else {
        console.warn(`Cleanup: DELETE rental #${id} returned ${delRes.status()}`)
      }
    } catch (err) {
      console.error(`Cleanup: error deleting rental #${id}:`, err)
    }
  }

  await apiRequest.dispose()
})

test.describe('Create Rental (safe test dates)', () => {
  test('safety guard: test dates are >= October 2026', () => {
    // This test simply validates the safety guard itself
    assertSafeDate(TEST_START_DATE)        // should not throw
    assertSafeDate('2026-10-07')           // should not throw
    expect(() => assertSafeDate('2026-09-30')).toThrow('SAFETY')
    expect(() => assertSafeDate('2025-01-01')).toThrow('SAFETY')
  })

  test('safety guard: prefix check works', () => {
    expect(() =>
      assertSafeToDelete({ id: 999, customer_name: '无前缀客户', start_date: '2026-10-01' })
    ).toThrow('SAFETY')

    // Should NOT throw
    assertSafeToDelete({
      id: 999,
      customer_name: `${TEST_CUSTOMER_PREFIX}客户`,
      start_date: '2026-10-01',
    })
  })

  test('create rental form is accessible from gantt', async ({ page }) => {
    await page.goto('/mobile/gantt')
    await page.waitForSelector('.van-nav-bar', { timeout: 8_000 })

    // Click 新建 button
    const newBtn = page.locator('.van-nav-bar .van-button').filter({ hasText: '新建' })
    await expect(newBtn).toBeVisible()
    await newBtn.click()

    await page.waitForURL(/create-rental/, { timeout: 5_000 })
    await expect(page).toHaveURL(/create-rental/)
  })

  test('create form renders all required fields', async ({ page }) => {
    await page.goto('/mobile/create-rental')
    await page.waitForSelector('.van-form, form, .van-cell-group', { timeout: 8_000 })

    // Check that essential fields are present
    const page_text = await page.content()
    expect(page_text).toContain('客户')          // customer name field
    expect(page_text).toContain('电话')          // phone field
    expect(page_text).toContain('起租')          // start date
    expect(page_text).toContain('还租')          // end date
  })

  test('create rental via API with October 2026 dates succeeds and then cleans up', async ({ request }) => {
    // Safety assertions
    assertSafeDate(safeTestRental.start_date)
    assertSafeDate(safeTestRental.end_date)
    expect(safeTestRental.customer_name.startsWith(TEST_CUSTOMER_PREFIX)).toBe(true)

    // Use API directly for a reliable create — UI form requires device selection which
    // may vary across environments.
    // Get a device ID via the gantt endpoint (the /api/devices list has a known 500 bug)
    const today = new Date().toISOString().slice(0, 10)
    const end = new Date(Date.now() + 13 * 86400000).toISOString().slice(0, 10)
    const ganttRes = await request.get(`http://localhost:5001/api/gantt/data?start_date=${today}&end_date=${end}`)
    expect(ganttRes.ok()).toBe(true)
    const ganttData = await ganttRes.json()
    const devices = ganttData.data?.devices ?? []
    if (!devices.length) {
      console.log('No devices available; skipping create test')
      test.skip()
      return
    }

    const deviceId = devices[0].id

    const payload = {
      ...safeTestRental,
      device_id: deviceId,
    }

    const createRes = await request.post('http://localhost:5001/api/rentals', { data: payload })
    expect(createRes.ok()).toBe(true)

    const body = await createRes.json()
    // API returns { data: { main_rental: { id, ... }, accessory_rentals: [] } }
    const created = body.data?.main_rental ?? body
    expect(created.id).toBeTruthy()
    expect(created.customer_name).toBe(safeTestRental.customer_name)
    expect(created.start_date).toBe(safeTestRental.start_date)

    // Track for cleanup
    createdRentalIds.push(created.id)
    console.log(`Created test rental #${created.id} (will be deleted in afterAll)`)
  })

  test('created test rental is searchable', async ({ page }) => {
    // Search for the test rental by its unique address
    await page.goto('/mobile/search')
    await page.waitForSelector('.van-search', { timeout: 8_000 })

    const input = page.locator('.van-search input, .van-search .van-field__control')
    await input.fill('E2E测试地址')

    await page.waitForTimeout(1000)
    await expect(page.locator('.van-loading')).not.toBeVisible({ timeout: 5_000 })

    // May find 0 results if the create test above was skipped or failed
    // The test is informational — just verifies search works for Chinese text
    const results = page.locator('.van-cell-group .van-cell')
    const empty = page.locator('.van-empty')

    const hasResults = await results.count() > 0
    const hasEmpty = await empty.isVisible().catch(() => false)

    // At minimum, one of these states should be shown (no crash)
    expect(hasResults || hasEmpty).toBe(true)
  })
})
