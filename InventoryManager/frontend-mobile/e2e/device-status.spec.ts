import { test, expect } from '@playwright/test'

/**
 * Device status view spec
 *
 * Verifies:
 *  1. Page loads at /mobile/device-status
 *  2. Device list is shown
 *  3. Lifecycle tab filters are present
 *  4. Tapping a lifecycle badge opens the lifecycle action sheet
 *
 * These tests are READ-ONLY for devices — we open action sheets but do NOT
 * confirm/submit any changes to avoid mutating production data.
 */

test.describe('Device Status View', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/mobile/device-status')
    await page.waitForSelector('.van-nav-bar', { timeout: 8_000 })
    // Wait for loading to complete — .device-list renders only when !ganttStore.loading
    await page.waitForSelector('.device-list, .van-empty', { timeout: 10_000 })
  })

  test('page loads with nav bar title 设备状态', async ({ page }) => {
    const title = page.locator('.van-nav-bar__title')
    await expect(title).toContainText('设备状态')
  })

  test('device list is rendered', async ({ page }) => {
    const fixtureNames = page.locator('.device-card .device-name').filter({
      hasText: /^E2E /,
    })
    await expect(fixtureNames).toHaveCount(7)
  })

  test('lifecycle filter tabs are present', async ({ page }) => {
    const tabs = page.locator('.van-tab')
    await expect(tabs).toHaveCount(6)
    for (const label of ['全部', '使用中', '已售出', '已停用', '已损坏', '已退役']) {
      await expect(tabs.filter({ hasText: label })).toBeVisible()
    }
  })

  test('clicking 使用中 filters to active devices only', async ({ page }) => {
    const activeTab = page.locator('.van-tab').filter({ hasText: '使用中' })
    await activeTab.click()
    await expect(page.locator('.device-card .device-name')).toHaveCount(3)
    await expect(page.locator('.device-card .lifecycle-badge')).toHaveText([
      '使用中',
      '使用中',
      '使用中',
    ])
  })

  test('tapping lifecycle badge opens lifecycle options', async ({ page }) => {
    const cards = page.locator('.device-card')
    await expect(cards).toHaveCount(7)

    const firstLifecycleTag = page.locator('.device-card .van-tag').first()
    await expect(firstLifecycleTag).toBeVisible()
    await firstLifecycleTag.click()
    const sheet = page.locator('.van-action-sheet')
    await expect(sheet).toBeVisible()
    const items = sheet.locator('.van-action-sheet__item')
    const itemTexts = await items.allTextContents()
    expect(itemTexts.some(t => t.includes('使用中'))).toBe(true)
    expect(itemTexts.some(t => t.includes('已售出'))).toBe(true)

    // Close without confirming (safety — no mutations)
    const cancel = sheet.locator('.van-action-sheet__cancel')
    if (await cancel.isVisible()) {
      await cancel.click()
    } else {
      await page.keyboard.press('Escape')
    }
  })

  test('back button navigates to previous page (gantt)', async ({ page }) => {
    // Navigate from gantt to device-status, then back
    await page.goto('/mobile/gantt')
    await page.waitForSelector('.van-nav-bar', { timeout: 8_000 })
    // Wait for gantt to fully render so nav buttons are clickable
    await page.waitForSelector('.van-nav-bar__right .van-button', { timeout: 8_000 })

    // Click the settings/device-status icon button (3rd from left = index 2 in right slot)
    const navBtns = page.locator('.van-nav-bar__right .van-button')
    const count = await navBtns.count()
    expect(count).toBeGreaterThanOrEqual(3)
    await navBtns.nth(count - 2).click()  // second-to-last = settings/device-status icon

    await page.waitForURL(/device-status/, { timeout: 8_000 })
    await expect(page).toHaveURL(/device-status/)

    // Click back
    const backBtn = page.locator('.van-nav-bar__left')
    await backBtn.click()
    await page.waitForURL(/gantt/, { timeout: 8_000 })
    await expect(page).toHaveURL(/gantt/)
  })
})
