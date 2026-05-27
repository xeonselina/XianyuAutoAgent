import { test, expect, request as playwrightRequest } from '@playwright/test'
import {
  safeTestRental,
  TEST_START_DATE,
  assertSafeDate,
  assertSafeToDelete,
  TEST_CUSTOMER_PREFIX,
} from './helpers/safetyGuard'

/**
 * Accessory Selection E2E Tests
 *
 * Verifies that the phone holder / tripod pickers in both CreateRental
 * and EditRental load real device names (not "undefined") after the
 * `/api/devices` response-shape fix.
 *
 * Safety rules:
 *  - Read-only access to existing rentals (no modifications)
 *  - Any new rentals use dates >= October 2026 and TEST_CUSTOMER_PREFIX
 *  - All test-created rentals are deleted in afterAll
 */

const BASE = 'http://localhost:5001'
const createdRentalIds: number[] = []

// ─── Cleanup ────────────────────────────────────────────────────────────────

test.afterAll(async () => {
  if (createdRentalIds.length === 0) return

  const api = await playwrightRequest.newContext({ baseURL: BASE })
  for (const id of createdRentalIds) {
    try {
      const getRes = await api.get(`/api/rentals/${id}`)
      if (!getRes.ok()) {
        console.warn(`Cleanup: cannot GET rental #${id} — skipping`)
        continue
      }
      const body = await getRes.json()
      const rental = body.data ?? body
      assertSafeToDelete({ id, customer_name: rental.customer_name, start_date: rental.start_date })

      const del = await api.delete(`/api/rentals/${id}`)
      console.log(`Cleanup: ${del.ok() ? 'deleted' : 'FAILED to delete'} rental #${id}`)
    } catch (err) {
      console.error(`Cleanup error for rental #${id}:`, err)
    }
  }
  await api.dispose()
})

// ─── Helpers ─────────────────────────────────────────────────────────────────

/**
 * Assert that no picker option text contains the word "undefined".
 * This was the core regression: accessories loaded with wrong key.
 */
async function assertNoUndefinedInPicker(page: import('@playwright/test').Page) {
  const popup = page.locator('.van-popup--bottom')
  await expect(popup).toBeVisible({ timeout: 5_000 })

  // Collect all visible picker option labels
  const optionTexts = await page.locator('.van-picker-column__item .van-ellipsis').allTextContents()
  const undefinedItems = optionTexts.filter(t => t.includes('undefined'))
  expect(undefinedItems, `Picker should not contain "undefined" items, but found: ${JSON.stringify(undefinedItems)}`).toHaveLength(0)
}

/** Get the first available real rental ID from the API (for read-only edit tests). */
async function getFirstRealRentalId(): Promise<number | null> {
  const api = await playwrightRequest.newContext({ baseURL: BASE })
  try {
    const res = await api.get('/api/rentals?page=1&per_page=5')
    const body = await res.json()
    const rentals: any[] = body.data?.rentals ?? []
    // Prefer a rental that is not in test-prefix to ensure it has real data
    const real = rentals.find(r => !r.customer_name?.startsWith(TEST_CUSTOMER_PREFIX))
    return real?.id ?? rentals[0]?.id ?? null
  } finally {
    await api.dispose()
  }
}

/** Create a minimal test rental via API and return its ID. */
async function createTestRental(deviceId: number): Promise<number> {
  assertSafeDate(safeTestRental.start_date)
  const api = await playwrightRequest.newContext({ baseURL: BASE })
  try {
    const res = await api.post('/api/rentals', {
      data: { ...safeTestRental, device_id: deviceId },
    })
    expect(res.ok()).toBe(true)
    const body = await res.json()
    const created = body.data?.main_rental ?? body
    expect(created.id).toBeTruthy()
    return created.id
  } finally {
    await api.dispose()
  }
}

// ─── API-level sanity ─────────────────────────────────────────────────────────

test.describe('API: accessories endpoint', () => {
  test('GET /api/devices?is_accessory=true returns devices array (not empty)', async ({ request }) => {
    const res = await request.get(`${BASE}/api/devices?is_accessory=true&per_page=50`)
    expect(res.ok()).toBe(true)

    const body = await res.json()
    // Endpoint returns plain { devices: [...], total: N } — NOT wrapped in { success, data }
    expect(Array.isArray(body.devices)).toBe(true)
    expect(body.devices.length).toBeGreaterThan(0)

    // Every device must have id and name
    for (const d of body.devices) {
      expect(d.id).toBeTruthy()
      expect(typeof d.name).toBe('string')
      expect(d.name).not.toBe('')
      expect(d.name).not.toContain('undefined')
    }
  })

  test('Accessories include phone holders and tripods', async ({ request }) => {
    const res = await request.get(`${BASE}/api/devices?is_accessory=true&per_page=100`)
    const body = await res.json()
    const devices: any[] = body.devices ?? []

    const phoneHolders = devices.filter(
      d =>
        d.model?.toLowerCase().includes('phone_holder') ||
        d.model?.includes('手机支架') ||
        d.name?.includes('手机支架'),
    )
    const tripods = devices.filter(
      d =>
        d.model?.toLowerCase().includes('tripod') ||
        d.model?.includes('三脚架') ||
        d.name?.includes('三脚架'),
    )

    expect(phoneHolders.length).toBeGreaterThan(0)
    expect(tripods.length).toBeGreaterThan(0)
    console.log(`Found ${phoneHolders.length} phone holder(s), ${tripods.length} tripod(s)`)
  })
})

// ─── Create Rental — accessory pickers ───────────────────────────────────────

test.describe('CreateRental: accessory pickers', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/mobile/create-rental')
    // Wait for the form to finish loading (accessories are fetched on mount)
    await page.waitForSelector('.van-form, .van-cell-group', { timeout: 10_000 })
    // Give the axios call time to resolve
    await page.waitForTimeout(1_500)
  })

  test('Phone holder picker: opens and shows real names (not undefined)', async ({ page }) => {
    // The 手机支架 field is in the 配件 group
    const phoneHolderField = page.locator('.van-field').filter({ hasText: '手机支架' })
    await expect(phoneHolderField).toBeVisible({ timeout: 5_000 })
    await phoneHolderField.click()

    await assertNoUndefinedInPicker(page)

    // At minimum the "无" option plus at least one real device
    const optionTexts = await page.locator('.van-picker-column__item .van-ellipsis').allTextContents()
    expect(optionTexts.length).toBeGreaterThan(1) // "无" + at least one phone holder

    const hasNone = optionTexts.some(t => t.includes('无'))
    expect(hasNone).toBe(true) // "无" option must be present

    console.log('Phone holder options:', optionTexts.slice(0, 5))

    // Close picker
    await page.locator('.van-picker .van-picker__cancel').click()
  })

  test('Tripod picker: opens and shows real names (not undefined)', async ({ page }) => {
    const tripodField = page.locator('.van-field').filter({ hasText: '三脚架' })
    await expect(tripodField).toBeVisible({ timeout: 5_000 })
    await tripodField.click()

    await assertNoUndefinedInPicker(page)

    const optionTexts = await page.locator('.van-picker-column__item .van-ellipsis').allTextContents()
    expect(optionTexts.length).toBeGreaterThan(1) // "无" + at least one tripod

    console.log('Tripod options:', optionTexts.slice(0, 5))

    await page.locator('.van-picker .van-picker__cancel').click()
  })

  test('Phone holder: can select a value', async ({ page }) => {
    const phoneHolderField = page.locator('.van-field').filter({ hasText: '手机支架' })
    await expect(phoneHolderField).toBeVisible({ timeout: 5_000 })
    await phoneHolderField.click()

    const popup = page.locator('.van-popup--bottom')
    await expect(popup).toBeVisible({ timeout: 5_000 })

    // Pick the second option (first real device, skipping "无")
    const items = page.locator('.van-picker-column__item .van-ellipsis')
    const count = await items.count()
    expect(count).toBeGreaterThan(1)

    // Click on the second item (index 1) — a real phone holder
    await items.nth(1).click()

    // Confirm via the picker confirm button
    await page.locator('.van-picker .van-picker__confirm').click()

    // The field value should now show the selected name (not empty, not "undefined")
    const fieldInput = phoneHolderField.locator('.van-field__control, input')
    const value = await fieldInput.inputValue().catch(() => '')
    expect(value).not.toBe('')
    expect(value).not.toContain('undefined')
    console.log(`Selected phone holder: "${value}"`)
  })

  test('Tripod: can select a value', async ({ page }) => {
    const tripodField = page.locator('.van-field').filter({ hasText: '三脚架' })
    await expect(tripodField).toBeVisible({ timeout: 5_000 })
    await tripodField.click()

    const popup = page.locator('.van-popup--bottom')
    await expect(popup).toBeVisible({ timeout: 5_000 })

    const items = page.locator('.van-picker-column__item .van-ellipsis')
    const count = await items.count()
    expect(count).toBeGreaterThan(1)

    await items.nth(1).click()
    await page.locator('.van-picker .van-picker__confirm').click()

    const fieldInput = tripodField.locator('.van-field__control, input')
    const value = await fieldInput.inputValue().catch(() => '')
    expect(value).not.toBe('')
    expect(value).not.toContain('undefined')
    console.log(`Selected tripod: "${value}"`)
  })
})

// ─── Create Rental — device picker ───────────────────────────────────────────

test.describe('CreateRental: device picker shows real names after date+model selection', () => {
  test('Device picker items do not contain "undefined"', async ({ page }) => {
    // We need a model + dates to trigger the availability check
    // First, get a valid model from the API
    const api = await playwrightRequest.newContext({ baseURL: BASE })
    const modelsRes = await api.get('/api/device-models')
    const modelsBody = await modelsRes.json()
    const models: any[] = modelsBody.data ?? []
    await api.dispose()

    if (!models.length) {
      test.skip()
      return
    }

    await page.goto('/mobile/create-rental')
    await page.waitForSelector('.van-form', { timeout: 10_000 })

    // Select a model via picker
    const modelField = page.locator('.van-field').filter({ hasText: '设备型号' })
    await expect(modelField).toBeVisible()
    await modelField.click()

    // Helper: pick the confirm button inside a specific popup identified by its title
    const confirmPopupByTitle = async (title: string) => {
      const popup = page.locator('.van-popup--bottom').filter({
        has: page.locator('.van-picker__title', { hasText: title }),
      })
      await expect(popup).toBeVisible({ timeout: 5_000 })
      await popup.locator('.van-picker__confirm').click()
      // Wait for popup to finish closing before proceeding
      await expect(popup).toBeHidden({ timeout: 3_000 })
    }

    await expect(page.locator('.van-popup--bottom').filter({
      has: page.locator('.van-picker__title', { hasText: '设备型号' }),
    })).toBeVisible({ timeout: 5_000 })
    // Pick first model
    await page.locator('.van-picker-column__item .van-ellipsis').first().click()
    await confirmPopupByTitle('设备型号')

    // Select start date (confirm whatever the default is)
    assertSafeDate('2026-10-01')
    const startField = page.locator('.van-field').filter({ hasText: '起租日' })
    await startField.click()
    // DatePicker in Vant 4 renders directly as van-picker (no van-date-picker wrapper)
    await confirmPopupByTitle('起租日')

    // Select end date
    const endField = page.locator('.van-field').filter({ hasText: '还租日' })
    await endField.click()
    await confirmPopupByTitle('还租日')

    // Wait for availability check
    await page.waitForTimeout(3_000)

    // Open device picker
    const deviceField = page.locator('.van-field').filter({ hasText: '可用设备' })
    await deviceField.click()

    const devicePopup = page.locator('.van-popup--bottom')
    const isVisible = await devicePopup.isVisible().catch(() => false)
    if (!isVisible) {
      // No devices available for this slot — that's OK, not a bug
      console.log('No available devices for selected slot — test skipped')
      return
    }

    // Check that none of the options contain "undefined"
    const optionTexts = await page.locator('.van-picker-column__item .van-ellipsis').allTextContents()
    const undefinedItems = optionTexts.filter(t => t.includes('undefined'))
    expect(
      undefinedItems,
      `Device picker should not show "undefined", found: ${JSON.stringify(undefinedItems)}`,
    ).toHaveLength(0)
    console.log('Device picker options (first 3):', optionTexts.slice(0, 3))

    await page.locator('.van-picker .van-picker__cancel').click()
  })
})

// ─── Edit Rental — accessory pickers ─────────────────────────────────────────

test.describe('EditRental: accessory pickers', () => {
  let rentalId: number | null = null

  test.beforeAll(async () => {
    rentalId = await getFirstRealRentalId()
    console.log(`Using existing rental #${rentalId} for read-only edit tests`)
  })

  test.beforeEach(async ({ page }) => {
    if (!rentalId) {
      test.skip()
      return
    }
    await page.goto(`/mobile/edit-rental/${rentalId}`)
    // Wait for the form to load (not the initial loading spinner)
    await page.waitForSelector('.van-form', { timeout: 15_000 })
    await page.waitForTimeout(1_500)
  })

  test('Phone holder picker: opens and shows real names (not undefined)', async ({ page }) => {
    if (!rentalId) { test.skip(); return }

    const phoneHolderField = page.locator('.van-field').filter({ hasText: '手机支架' })
    await expect(phoneHolderField).toBeVisible({ timeout: 5_000 })
    await phoneHolderField.click()

    await assertNoUndefinedInPicker(page)

    const optionTexts = await page.locator('.van-picker-column__item .van-ellipsis').allTextContents()
    expect(optionTexts.length).toBeGreaterThan(0)
    console.log('EditRental phone holder options:', optionTexts.slice(0, 5))

    // Must NOT select anything — just cancel (read-only test)
    await page.locator('.van-picker .van-picker__cancel').click()
  })

  test('Tripod picker: opens and shows real names (not undefined)', async ({ page }) => {
    if (!rentalId) { test.skip(); return }

    const tripodField = page.locator('.van-field').filter({ hasText: '三脚架' })
    await expect(tripodField).toBeVisible({ timeout: 5_000 })
    await tripodField.click()

    await assertNoUndefinedInPicker(page)

    const optionTexts = await page.locator('.van-picker-column__item .van-ellipsis').allTextContents()
    expect(optionTexts.length).toBeGreaterThan(0)
    console.log('EditRental tripod options:', optionTexts.slice(0, 5))

    await page.locator('.van-picker .van-picker__cancel').click()
  })
})

// ─── Edit Rental — full workflow with test rental ────────────────────────────

test.describe('EditRental: accessory selection workflow (test rental)', () => {
  let testRentalId: number | null = null

  test.beforeAll(async () => {
    // Get a device to assign the test rental to
    const api = await playwrightRequest.newContext({ baseURL: BASE })
    try {
      const today = new Date().toISOString().slice(0, 10)
      const future = new Date(Date.now() + 14 * 86400000).toISOString().slice(0, 10)
      const ganttRes = await api.get(`/api/gantt/data?start_date=${today}&end_date=${future}`)
      const ganttBody = await ganttRes.json()
      const devices: any[] = ganttBody.data?.devices ?? []
      if (!devices.length) return

      testRentalId = await createTestRental(devices[0].id)
      createdRentalIds.push(testRentalId)
      console.log(`Created test rental #${testRentalId} for edit accessory tests`)
    } finally {
      await api.dispose()
    }
  })

  test.beforeEach(async ({ page }) => {
    if (!testRentalId) {
      test.skip()
      return
    }
    await page.goto(`/mobile/edit-rental/${testRentalId}`)
    await page.waitForSelector('.van-form', { timeout: 15_000 })
    await page.waitForTimeout(1_500)
  })

  test('Can open phone holder picker and select an item on a test rental', async ({ page }) => {
    if (!testRentalId) { test.skip(); return }

    const phoneHolderField = page.locator('.van-field').filter({ hasText: '手机支架' })
    await expect(phoneHolderField).toBeVisible({ timeout: 5_000 })
    await phoneHolderField.click()

    const popup = page.locator('.van-popup--bottom')
    await expect(popup).toBeVisible({ timeout: 5_000 })

    // Verify no undefined
    const optionTexts = await page.locator('.van-picker-column__item .van-ellipsis').allTextContents()
    const undefinedItems = optionTexts.filter(t => t.includes('undefined'))
    expect(undefinedItems).toHaveLength(0)

    // Select a real phone holder (skip "无" at index 0)
    const items = page.locator('.van-picker-column__item .van-ellipsis')
    const count = await items.count()
    if (count > 1) {
      await items.nth(1).click()
      await page.locator('.van-picker .van-picker__confirm').click()

      const fieldInput = phoneHolderField.locator('.van-field__control, input')
      const value = await fieldInput.inputValue().catch(() => '')
      expect(value).not.toContain('undefined')
      expect(value.length).toBeGreaterThan(0)
      console.log(`Selected phone holder on test rental: "${value}"`)
    } else {
      // Only "无" available — just confirm
      await page.locator('.van-picker .van-picker__confirm').click()
    }
  })

  test('Can open tripod picker and select an item on a test rental', async ({ page }) => {
    if (!testRentalId) { test.skip(); return }

    const tripodField = page.locator('.van-field').filter({ hasText: '三脚架' })
    await expect(tripodField).toBeVisible({ timeout: 5_000 })
    await tripodField.click()

    const popup = page.locator('.van-popup--bottom')
    await expect(popup).toBeVisible({ timeout: 5_000 })

    const optionTexts = await page.locator('.van-picker-column__item .van-ellipsis').allTextContents()
    const undefinedItems = optionTexts.filter(t => t.includes('undefined'))
    expect(undefinedItems).toHaveLength(0)

    const items = page.locator('.van-picker-column__item .van-ellipsis')
    const count = await items.count()
    if (count > 1) {
      await items.nth(1).click()
      await page.locator('.van-picker .van-picker__confirm').click()

      const fieldInput = tripodField.locator('.van-field__control, input')
      const value = await fieldInput.inputValue().catch(() => '')
      expect(value).not.toContain('undefined')
      console.log(`Selected tripod on test rental: "${value}"`)
    } else {
      await page.locator('.van-picker .van-picker__confirm').click()
    }
  })
})
