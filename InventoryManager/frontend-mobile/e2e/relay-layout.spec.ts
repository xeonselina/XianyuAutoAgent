import { expect, test } from '@playwright/test'

const DESKTOP_URL = 'http://127.0.0.1:5002/relay-management'
const MOBILE_URL = 'http://127.0.0.1:5003/mobile/relay'

test('desktop relay table scrolls at 1280px while actions stay fixed', async ({ browser }, testInfo) => {
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } })
  await page.goto(DESKTOP_URL)
  await expect(page.getByTestId('relay-wide-table')).toBeVisible()
  await expect(page.getByText('SF1234567890')).toBeVisible()

  const metrics = await page.evaluate(() => {
    const scroll = document.querySelector('.el-scrollbar__wrap') as HTMLElement
    const action = Array.from(document.querySelectorAll('.el-table-fixed-column--right'))
      .find(element => element.textContent?.includes('维护')) as HTMLElement
    return {
      viewportWidth: window.innerWidth,
      pageScrollWidth: document.documentElement.scrollWidth,
      tableClientWidth: scroll.clientWidth,
      tableScrollWidth: scroll.scrollWidth,
      actionRight: action.getBoundingClientRect().right,
      actionPosition: getComputedStyle(action).position,
    }
  })

  expect(metrics.pageScrollWidth).toBeLessThanOrEqual(metrics.viewportWidth)
  expect(metrics.tableScrollWidth).toBeGreaterThan(metrics.tableClientWidth)
  expect(metrics.actionPosition).toBe('sticky')
  expect(metrics.actionRight).toBeLessThanOrEqual(metrics.viewportWidth)
  await page.screenshot({ path: testInfo.outputPath('relay-desktop-1280.png'), fullPage: true })
  await page.close()
})

test('desktop relay table expands without horizontal scroll at 4K', async ({ browser }, testInfo) => {
  const page = await browser.newPage({ viewport: { width: 3840, height: 1400 } })
  await page.goto(DESKTOP_URL)
  await expect(page.getByTestId('relay-wide-table')).toBeVisible()

  const metrics = await page.evaluate(() => {
    const scroll = document.querySelector('.el-scrollbar__wrap') as HTMLElement
    return {
      viewportWidth: window.innerWidth,
      pageScrollWidth: document.documentElement.scrollWidth,
      tableClientWidth: scroll.clientWidth,
      tableScrollWidth: scroll.scrollWidth,
    }
  })

  expect(metrics.pageScrollWidth).toBeLessThanOrEqual(metrics.viewportWidth)
  expect(metrics.tableScrollWidth).toBeLessThanOrEqual(metrics.tableClientWidth + 1)
  await page.screenshot({ path: testInfo.outputPath('relay-desktop-4k.png'), fullPage: true })
  await page.close()
})

test('mobile relay card fits 390px and keeps touch actions at least 44px', async ({ browser }, testInfo) => {
  const page = await browser.newPage({ viewport: { width: 390, height: 844 } })
  await page.goto(MOBILE_URL)
  const card = page.getByTestId('relay-card')
  await expect(card).toBeVisible()
  await expect(page.getByText('SF1234567890')).toBeVisible()

  const beforeSheet = await page.evaluate(() => {
    const card = document.querySelector('[data-testid="relay-card"]') as HTMLElement
    const maintain = document.querySelector('[data-testid="relay-maintain"]') as HTMLElement
    const filter = document.querySelector('[data-testid="relay-date-filter"]') as HTMLElement
    return {
      viewportWidth: window.innerWidth,
      pageScrollWidth: document.documentElement.scrollWidth,
      cardLeft: card.getBoundingClientRect().left,
      cardRight: card.getBoundingClientRect().right,
      maintainHeight: maintain.getBoundingClientRect().height,
      filterHeight: filter.getBoundingClientRect().height,
    }
  })

  expect(beforeSheet.pageScrollWidth).toBeLessThanOrEqual(beforeSheet.viewportWidth)
  expect(beforeSheet.cardLeft).toBeGreaterThanOrEqual(0)
  expect(beforeSheet.cardRight).toBeLessThanOrEqual(beforeSheet.viewportWidth)
  expect(beforeSheet.maintainHeight).toBeGreaterThanOrEqual(44)
  expect(beforeSheet.filterHeight).toBeGreaterThanOrEqual(44)

  await page.getByTestId('relay-maintain').click()
  const statusButtons = page.locator('.status-option')
  await expect(statusButtons).toHaveCount(5)
  await expect(statusButtons.first()).toBeVisible()
  const heights = await statusButtons.evaluateAll(elements =>
    elements.map(element => element.getBoundingClientRect().height),
  )
  expect(heights.every(height => height >= 44)).toBe(true)
  await page.screenshot({ path: testInfo.outputPath('relay-mobile-390.png'), fullPage: true })
  await page.close()
})
