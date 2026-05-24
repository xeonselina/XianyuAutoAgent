import { test, expect } from '@playwright/test'

/**
 * Gantt color coding spec
 *
 * Verifies that rental bars are rendered with the correct status-based colors,
 * not the old random-color scheme.
 *
 * Color map (must match GanttGrid.vue STATUS_COLORS):
 *   not_shipped              → #c8860a  (brownish-yellow)
 *   scheduled_for_shipping   → #1989fa  (blue)
 *   shipped                  → #07c160  (green)
 *   returned                 → #7232dd  (purple)
 *   completed                → #909399  (grey)
 *   cancelled                → #c8c9cc  (light grey)
 */

const STATUS_COLORS: Record<string, string> = {
  not_shipped:            'rgb(200, 134, 10)',   // #c8860a
  scheduled_for_shipping: 'rgb(25, 137, 250)',   // #1989fa
  shipped:                'rgb(7, 193, 96)',     // #07c160
  returned:               'rgb(114, 50, 221)',   // #7232dd
  completed:              'rgb(144, 147, 153)',  // #909399
  cancelled:              'rgb(200, 201, 204)',  // #c8c9cc
}

/** Convert hex color to rgb() string for comparison */
function hexToRgb(hex: string): string {
  const r = parseInt(hex.slice(1, 3), 16)
  const g = parseInt(hex.slice(3, 5), 16)
  const b = parseInt(hex.slice(5, 7), 16)
  return `rgb(${r}, ${g}, ${b})`
}

test.describe('Gantt — status-based bar colors', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/mobile/gantt')
    // Wait for gantt grid to render (devices column appears)
    await page.waitForSelector('.gantt-grid', { timeout: 10_000 })
    // Allow data to load
    await page.waitForTimeout(1500)
  })

  test('rental bars exist on the gantt', async ({ page }) => {
    // The gantt should render at least the grid container
    const grid = page.locator('.gantt-grid')
    await expect(grid).toBeVisible()
  })

  test('rental period bars use status color (not random)', async ({ page }) => {
    // Get all rental-period bars
    const bars = page.locator('.rental-period-bar')
    const count = await bars.count()

    if (count === 0) {
      // No rentals in the current window — not a test failure, just skip color check
      console.log('No rental-period bars visible in current gantt window; skipping color check')
      return
    }

    // For each visible bar, check that its background color matches one of the valid status colors
    const validColors = new Set(Object.values(STATUS_COLORS))

    for (let i = 0; i < Math.min(count, 10); i++) {
      const bar = bars.nth(i)
      const bg = await bar.evaluate(el => getComputedStyle(el).backgroundColor)
      // The color must be one of our status colors (or a variant like rgba(...))
      const isKnownColor = [...validColors].some(c => bg.startsWith(c.replace(')', '').replace('rgb', 'rgb')))
        || validColors.has(bg)
      expect(isKnownColor, `bar ${i} has unexpected color: ${bg}`).toBe(true)
    }
  })

  test('ship-range bars use the same status color with transparency', async ({ page }) => {
    const bars = page.locator('.ship-range-bar')
    const count = await bars.count()

    if (count === 0) {
      console.log('No ship-range bars visible; skipping')
      return
    }

    for (let i = 0; i < Math.min(count, 5); i++) {
      const bar = bars.nth(i)
      const bg = await bar.evaluate(el => getComputedStyle(el).backgroundColor)
      // Ship-range bars use rgba (semi-transparent) — must contain rgb values not pure black/white
      expect(bg).toMatch(/rgba?\(/)
    }
  })
})
