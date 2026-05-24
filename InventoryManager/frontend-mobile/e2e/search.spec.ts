import { test, expect } from '@playwright/test'

/**
 * Search spec
 *
 * Verifies:
 *  1. Search view loads at /mobile/search (or via nav icon)
 *  2. Empty state shows hint text before search
 *  3. Typing a keyword triggers debounced search and shows results
 *  4. Empty results show "未找到相关记录"
 *  5. Tapping a result navigates to the edit-rental page
 *
 * Strategy: search by a common Chinese character or number that's likely
 * to match real records (read-only). No rental mutations.
 */

test.describe('Search View', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/mobile/search')
    await page.waitForSelector('.van-search', { timeout: 8_000 })
  })

  test('page loads with search bar visible', async ({ page }) => {
    const searchBar = page.locator('.van-search')
    await expect(searchBar).toBeVisible()
  })

  test('hint text is shown before any search', async ({ page }) => {
    // The initial state should show the hint (no search performed yet)
    const hint = page.locator('.hint-text')
    await expect(hint).toBeVisible()
    await expect(hint).toContainText('输入电话或地址关键词')
  })

  test('searching for a common term returns results or empty state', async ({ page }) => {
    const input = page.locator('.van-search input, .van-search .van-field__control')
    await input.fill('1')

    // Wait for debounce (400ms) + network
    await page.waitForTimeout(1000)

    // Either results are shown OR the empty state
    const results = page.locator('.van-cell-group .van-cell')
    const empty = page.locator('.van-empty')
    const loading = page.locator('.van-loading')

    // Wait for loading to finish
    await expect(loading).not.toBeVisible({ timeout: 5_000 })

    const hasResults = await results.count() > 0
    const hasEmpty = await empty.isVisible()
    expect(hasResults || hasEmpty).toBe(true)
  })

  test('searching for a nonexistent string shows 未找到相关记录', async ({ page }) => {
    const input = page.locator('.van-search input, .van-search .van-field__control')
    // Use a unique string that won't match any real record
    await input.fill('XYZNOTEXIST99999')

    await page.waitForTimeout(800)

    const empty = page.locator('.van-empty')
    await expect(empty).toBeVisible({ timeout: 5_000 })
    await expect(empty).toContainText('未找到相关记录')
  })

  test('clearing input resets to hint state', async ({ page }) => {
    const input = page.locator('.van-search input, .van-search .van-field__control')
    await input.fill('test')
    await page.waitForTimeout(200)

    // Clear the input
    await input.fill('')
    await page.waitForTimeout(200)

    // Hint should reappear
    const hint = page.locator('.hint-text')
    await expect(hint).toBeVisible({ timeout: 3_000 })
  })

  test('tapping a result navigates to edit-rental page', async ({ page }) => {
    const input = page.locator('.van-search input, .van-search .van-field__control')
    // Search for something likely to return results
    await input.fill('1')
    await page.waitForTimeout(1000)

    const results = page.locator('.van-cell-group .van-cell')
    await expect(page.locator('.van-loading')).not.toBeVisible({ timeout: 5_000 })

    const count = await results.count()
    if (count === 0) {
      console.log('No search results found for "1"; skipping navigation test')
      test.skip()
      return
    }

    // Tap the first result
    await results.first().click()

    // Should navigate to edit-rental
    await page.waitForURL(/edit-rental\/\d+/, { timeout: 5_000 })
    await expect(page).toHaveURL(/edit-rental\/\d+/)
  })

  test('can navigate to search from gantt nav bar', async ({ page }) => {
    await page.goto('/mobile/gantt')
    await page.waitForSelector('.van-nav-bar', { timeout: 8_000 })

    // The search icon button is in the nav-bar right slot
    const searchBtn = page.locator('.van-nav-bar__right .van-button .van-icon-search')
      .or(page.locator('.van-nav-bar__right .van-icon-search'))
    if (!await searchBtn.isVisible({ timeout: 2_000 })) {
      // Try clicking the button that has a search icon
      const navBtns = page.locator('.van-nav-bar__right .van-button')
      const btnCount = await navBtns.count()
      if (btnCount >= 2) {
        // search button is second from left among right buttons (after filter)
        // order: 筛选, search, settings, 新建
        await navBtns.nth(1).click()
      }
    } else {
      await searchBtn.click()
    }

    await page.waitForURL(/search/, { timeout: 5_000 })
    await expect(page).toHaveURL(/search/)
  })
})
