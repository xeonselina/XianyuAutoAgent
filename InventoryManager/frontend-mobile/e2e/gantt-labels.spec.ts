import { test, expect } from '@playwright/test'

/**
 * Gantt label readability spec
 *
 * Verifies the "floating label" design introduced to fix the 1-day rental
 * truncation problem:
 *
 *  - Labels are rendered as `.bar-label-float` elements (siblings to the bars,
 *    NOT children of the colored bar div).
 *  - Each label shows: customer_name + "·" + last-4-digits-of-phone on one line.
 *  - Labels are positioned at the same left edge as their rental-period-bar.
 *  - Text is visually readable: the label element must not have overflow:hidden
 *    and must have white-space:nowrap so it extends beyond narrow bars.
 *  - The original `.bar-label` span inside the bar NO LONGER exists.
 *
 * Read-only — no mutations to the DB.
 */

test.describe('Gantt — floating rental labels', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/mobile/gantt')
    await page.waitForSelector('.gantt-grid', { timeout: 10_000 })
    await page.waitForTimeout(1500)
  })

  test('bar-label-float elements exist when rental bars are present', async ({ page }) => {
    const bars = page.locator('.rental-period-bar')
    const labels = page.locator('.bar-label-float')
    const barCount = await bars.count()

    if (barCount === 0) {
      console.log('No rental bars in current window; skipping label check')
      return
    }

    const labelCount = await labels.count()
    // Every rental-period-bar should have a corresponding bar-label-float
    expect(labelCount).toBe(barCount)
  })

  test('old bar-label span no longer exists inside rental bars', async ({ page }) => {
    // The old implementation put text inside the bar; after the fix it must be gone
    const oldLabel = page.locator('.rental-period-bar .bar-label')
    await expect(oldLabel).toHaveCount(0)
  })

  test('label contains customer name text', async ({ page }) => {
    const labels = page.locator('.bar-label-float')
    const count = await labels.count()

    if (count === 0) {
      console.log('No labels found; skipping')
      return
    }

    // At least one label should have non-empty name text
    const firstNameSpan = labels.first().locator('.bar-label-name')
    const nameText = await firstNameSpan.textContent()
    expect(nameText?.trim().length).toBeGreaterThan(0)
  })

  test('phone part shows ·XXXX format (last 4 digits)', async ({ page }) => {
    const phoneSpans = page.locator('.bar-label-float .bar-label-phone')
    const count = await phoneSpans.count()

    if (count === 0) {
      console.log('No phone spans visible (all rentals may lack phone numbers); skipping')
      return
    }

    for (let i = 0; i < Math.min(count, 5); i++) {
      const text = await phoneSpans.nth(i).textContent()
      // Must match ·NNNN (middle-dot + exactly 4 digits)
      expect(text?.trim()).toMatch(/^·\d{4}$/)
    }
  })

  test('label is positioned at same left offset as its rental-period-bar', async ({ page }) => {
    const bars = page.locator('.rental-period-bar')
    const labels = page.locator('.bar-label-float')
    const count = await bars.count()

    if (count === 0) {
      console.log('No bars to compare; skipping')
      return
    }

    // Compare first bar's left position with first label's left position
    const barLeft = await bars.first().evaluate(el => el.getBoundingClientRect().left)
    const labelLeft = await labels.first().evaluate(el => el.getBoundingClientRect().left)

    // Allow ±4px tolerance (padding difference)
    expect(Math.abs(barLeft - labelLeft)).toBeLessThanOrEqual(4)
  })

  test('label text is not clipped by overflow:hidden', async ({ page }) => {
    const labels = page.locator('.bar-label-float')
    const count = await labels.count()

    if (count === 0) {
      console.log('No labels found; skipping')
      return
    }

    // Check that the label div itself does NOT have overflow:hidden
    const overflow = await labels.first().evaluate(
      el => getComputedStyle(el).overflow
    )
    expect(overflow).not.toBe('hidden')
  })

  test('label has white-space:nowrap so it extends beyond narrow bars', async ({ page }) => {
    const labels = page.locator('.bar-label-float')
    const count = await labels.count()

    if (count === 0) {
      console.log('No labels found; skipping')
      return
    }

    const whiteSpace = await labels.first().evaluate(
      el => getComputedStyle(el).whiteSpace
    )
    expect(whiteSpace).toBe('nowrap')
  })

  test('label is vertically centered within its row (26px row)', async ({ page }) => {
    const rows = page.locator('.gantt-row')
    const rowCount = await rows.count()

    if (rowCount === 0) {
      console.log('No gantt rows found; skipping')
      return
    }

    // Find a row that has a label
    for (let i = 0; i < Math.min(rowCount, 5); i++) {
      const label = rows.nth(i).locator('.bar-label-float').first()
      if (await label.count() === 0) continue

      const rowBox  = await rows.nth(i).boundingBox()
      const labelBox = await label.boundingBox()

      if (!rowBox || !labelBox) continue

      // Label center should be within the row vertically
      const labelCenterY = labelBox.y + labelBox.height / 2
      const rowCenterY   = rowBox.y  + rowBox.height  / 2
      expect(Math.abs(labelCenterY - rowCenterY)).toBeLessThanOrEqual(5)
      break
    }
  })
})
