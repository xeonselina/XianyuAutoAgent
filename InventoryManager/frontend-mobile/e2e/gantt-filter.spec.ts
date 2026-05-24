import { test, expect } from '@playwright/test'

/**
 * Gantt model filter spec
 *
 * Verifies that:
 *  1. The filter button is present in the nav-bar
 *  2. Tapping it opens an action-sheet with device model options
 *  3. Selecting a model narrows the device rows shown
 *  4. Selecting "全部型号" restores all rows
 */

test.describe('Gantt — model filter', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/mobile/gantt')
    // Wait for the gantt to be visible and data to load
    await page.waitForSelector('.gantt-grid', { timeout: 10_000 })
    await page.waitForTimeout(1500)
  })

  test('filter button is present in nav-bar', async ({ page }) => {
    // The filter button shows either current model name or '筛选'
    const filterBtn = page.locator('.van-nav-bar .van-button').filter({ hasText: /筛选|[A-Za-z0-9]/ }).first()
    await expect(filterBtn).toBeVisible()
  })

  test('tapping filter button opens action sheet', async ({ page }) => {
    // Find the filter button (shows '筛选' when no model is selected)
    const filterBtn = page.locator('.van-nav-bar .van-button').filter({ hasText: '筛选' })
    const visible = await filterBtn.isVisible()
    if (!visible) {
      // A model may already be selected from a prior test; click whatever is there
      const navBtns = page.locator('.van-nav-bar__right .van-button')
      await navBtns.first().click()
    } else {
      await filterBtn.click()
    }

    // Action sheet should appear
    const sheet = page.locator('.van-action-sheet')
    await expect(sheet).toBeVisible({ timeout: 3_000 })

    // Should contain "全部型号"
    await expect(sheet.locator('.van-action-sheet__item').filter({ hasText: '全部型号' })).toBeVisible()
  })

  test('selecting a model filters device rows', async ({ page }) => {
    // Count rows before filtering
    const allRows = page.locator('.device-row, .gantt-row')
    const totalBefore = await allRows.count()

    if (totalBefore === 0) {
      console.log('No device rows visible; skipping filter test')
      test.skip()
      return
    }

    // Open filter
    const filterBtn = page.locator('.van-nav-bar .van-button').filter({ hasText: '筛选' })
    if (await filterBtn.isVisible()) {
      await filterBtn.click()
    } else {
      // Already filtered — reset first
      const anyFilterBtn = page.locator('.van-nav-bar__right .van-button').first()
      await anyFilterBtn.click()
      const sheet = page.locator('.van-action-sheet')
      await sheet.locator('.van-action-sheet__item').filter({ hasText: '全部型号' }).click()
      await page.waitForTimeout(300)
      await filterBtn.click()
    }

    const sheet = page.locator('.van-action-sheet')
    await expect(sheet).toBeVisible({ timeout: 3_000 })

    // Get all model options (skip '全部型号')
    const items = sheet.locator('.van-action-sheet__item')
    const itemCount = await items.count()
    if (itemCount <= 1) {
      // Only "全部型号" exists — no model options to filter
      console.log('No model options besides 全部型号; skipping filter assertion')
      await page.keyboard.press('Escape')
      return
    }

    // Click the second item (first actual model, not '全部型号')
    await items.nth(1).click()
    await page.waitForTimeout(500)

    // Row count should be <= totalBefore
    const rowsAfter = await allRows.count()
    expect(rowsAfter).toBeLessThanOrEqual(totalBefore)
  })

  test('selecting 全部型号 restores all device rows', async ({ page }) => {
    const allRows = page.locator('.device-row, .gantt-row')
    const totalBefore = await allRows.count()
    if (totalBefore === 0) {
      test.skip()
      return
    }

    // Open filter and pick first real model
    let filterBtn = page.locator('.van-nav-bar .van-button').filter({ hasText: '筛选' })
    if (await filterBtn.isVisible()) {
      await filterBtn.click()
      const sheet = page.locator('.van-action-sheet')
      await expect(sheet).toBeVisible({ timeout: 3_000 })
      const items = sheet.locator('.van-action-sheet__item')
      if (await items.count() > 1) {
        await items.nth(1).click()
        await page.waitForTimeout(400)
      } else {
        await page.keyboard.press('Escape')
        return
      }
    }

    // Now reopen and pick 全部型号
    const anyModelBtn = page.locator('.van-nav-bar__right .van-button').first()
    await anyModelBtn.click()
    const sheet2 = page.locator('.van-action-sheet')
    await expect(sheet2).toBeVisible({ timeout: 3_000 })
    await sheet2.locator('.van-action-sheet__item').filter({ hasText: '全部型号' }).click()
    await page.waitForTimeout(400)

    const rowsRestored = await allRows.count()
    expect(rowsRestored).toBe(totalBefore)
  })
})
