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
    // Should have at least some device cards or a loading/empty state
    const cards = page.locator('.device-card')
    const empty = page.locator('.van-empty')

    // Either some cards are shown, or an empty state
    const hasCards = await cards.count() > 0
    const hasEmpty = await empty.count() > 0
    expect(hasCards || hasEmpty).toBe(true)
  })

  test('lifecycle filter tabs are present', async ({ page }) => {
    // van-tabs or custom tab buttons
    const tabs = page.locator('.van-tab, .van-tabs__nav .van-tab')
    const tabCount = await tabs.count()
    if (tabCount === 0) {
      // Maybe rendered as van-tabs__wrap
      const tabsWrap = page.locator('.van-tabs')
      await expect(tabsWrap).toBeVisible()
      return
    }
    expect(tabCount).toBeGreaterThanOrEqual(6)
    await expect(page.locator('.van-tab').filter({ hasText: '使用中' })).toBeVisible()
    await expect(page.locator('.van-tab').filter({ hasText: '已售出' })).toBeVisible()
  })

  test('clicking 使用中 filters to active devices only', async ({ page }) => {
    const activeTab = page.locator('.van-tab').filter({ hasText: '使用中' })
    if (!await activeTab.isVisible()) {
      console.log('使用中 tab not found; skipping')
      return
    }

    await activeTab.click()
    await page.waitForTimeout(400)

    const inactiveBadges = page.locator('.van-tag').filter({
      hasText: /已售出|已停用|已损坏|已退役/,
    })
    expect(await inactiveBadges.count()).toBe(0)
  })

  test('tapping lifecycle badge opens lifecycle options', async ({ page }) => {
    const cards = page.locator('.device-card')
    if (await cards.count() === 0) {
      console.log('No device cards; skipping action sheet test')
      test.skip()
      return
    }

    const firstLifecycleTag = page.locator('.device-card .van-tag').first()
    if (!await firstLifecycleTag.isVisible()) {
      console.log('No lifecycle tag found; skipping')
      return
    }

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
    if (count < 3) {
      console.log(`Only ${count} nav buttons found; skipping`)
      return
    }
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
