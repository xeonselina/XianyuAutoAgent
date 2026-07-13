import { expect, test, type Page } from '@playwright/test'

import type { Rental } from '../src/stores/gantt'
import { buildRentalConfirmation } from '../src/utils/rentalConfirmation'

const rental = (overrides: Partial<Rental> = {}): Rental => ({
  id: 42,
  device_id: 8,
  device: {
    id: 8,
    name: '3618',
    serial_number: 'SN-PRIVATE',
    model: 'x300u',
    device_model: {
      id: 3,
      name: 'x300u',
      display_name: 'VIVO X300 Ultra',
      is_active: true,
      created_at: '2026-01-01',
      updated_at: '2026-01-01',
      accessories: [],
    },
  },
  start_date: '2026-07-14',
  end_date: '2026-07-20',
  ship_out_time: '2026-07-12T19:30:00',
  ship_in_time: '2026-07-22T12:00:00',
  customer_name: '闲鱼用户ABC',
  customer_phone: '13800138000',
  destination: '张三，广东省广州市天河区一号路',
  status: 'not_shipped',
  includes_handle: true,
  includes_lens_mount: true,
  photo_transfer: true,
  lens_combo: 'lens_dual',
  accessories: [
    { name: '手机支架 12', model: '手机支架', type: 'phone_holder', is_bundled: false },
    { name: '备用手机支架', model: 'phone holder', type: 'phone_holder', is_bundled: false },
    { name: '三脚架 03', model: '三脚架', type: 'tripod', is_bundled: false },
  ],
  xianyu_order_no: 'XY-PRIVATE',
  buyer_id: 'BUYER-PRIVATE',
  ...overrides,
})

test.describe('mobile rental confirmation formatter', () => {
  test('formatter: generates exact five lines and excludes sensitive fields', () => {
    const result = buildRentalConfirmation(rental())

    expect(result.lines).toEqual([
      '收货地址：张三，广东省广州市天河区一号路，13800138000',
      '寄出时间：2026-07-12',
      '预计收货：2026-07-14',
      '客户归还：2026-07-20',
      '寄出型号：VIVO X300 Ultra + 双镜头 + 镜头支架 + 手柄 + 手机支架 + 三脚架',
    ])
    expect(result.text).toBe(result.lines.join('\n'))
    expect(result.text.split('\n')).toHaveLength(5)
    expect(result.text).not.toContain('2026-07-22')
    expect(result.text).not.toContain('闲鱼用户ABC')
    expect(result.text).not.toContain('SN-PRIVATE')
    expect(result.text).not.toContain('XY-PRIVATE')
    expect(result.text).not.toContain('BUYER-PRIVATE')
  })

  test('formatter: rejects malformed and calendar-invalid dates', () => {
    const result = buildRentalConfirmation(rental({
      ship_out_time: '2026-02-31T19:30:00',
      start_date: '2026/02/28',
      end_date: '2026-04-31',
    }))

    expect(result.lines.slice(1, 4)).toEqual([
      '寄出时间：未填写',
      '预计收货：未填写',
      '客户归还：未填写',
    ])
  })

  test('formatter: does not append a phone already present in formatted form', () => {
    const result = buildRentalConfirmation(rental({
      destination: '张三 138-0013-8000 广东省广州市',
    }))

    expect(result.lines[0]).toBe('收货地址：张三 138-0013-8000 广东省广州市')
  })

  test('formatter: uses fixed missing-value and no-accessory fallbacks', () => {
    const result = buildRentalConfirmation(rental({
      destination: '',
      customer_phone: '',
      ship_out_time: undefined,
      start_date: '',
      end_date: '',
      device: undefined,
      lens_combo: undefined,
      includes_handle: false,
      includes_lens_mount: false,
      accessories: [],
    }))

    expect(result.lines).toEqual([
      '收货地址：未填写',
      '寄出时间：未填写',
      '预计收货：未填写',
      '客户归还：未填写',
      '寄出型号：未识别型号 + 未填写镜头组合 + 无附件',
    ])
  })

  test('formatter: keeps and de-duplicates other actual accessories', () => {
    const result = buildRentalConfirmation(rental({
      includes_handle: false,
      includes_lens_mount: false,
      accessories: [
        { name: '补光灯', type: 'other', is_bundled: false },
        { name: '补光灯', type: 'other', is_bundled: false },
      ],
    }))

    expect(result.lines[4]).toBe('寄出型号：VIVO X300 Ultra + 双镜头 + 补光灯')
  })
})

const mockEditSave = async (
  page: Page,
  options: { refreshedRental?: Rental | null } = {},
) => {
  const refreshedRental = options.refreshedRental === undefined
    ? rental({ destination: '重查地址，广东省深圳市南山区' })
    : options.refreshedRental
  let rentalGets = 0

  await page.route('**/api/**', async route => {
    const url = new URL(route.request().url())
    if (url.pathname === '/api/gantt/data') {
      await route.fulfill({
        json: {
          success: true,
          data: {
            devices: [{
              id: 8,
              name: '3618',
              serial_number: 'SN-PRIVATE',
              model: 'x300u',
              is_accessory: false,
              status: 'online',
              lifecycle_status: 'active',
              created_at: '2026-01-01',
              updated_at: '2026-01-01',
            }],
            rentals: [],
          },
        },
      })
      return
    }
    if (url.pathname === '/api/devices') {
      await route.fulfill({ json: { devices: [] } })
      return
    }
    if (url.pathname === '/api/rentals/42') {
      rentalGets += 1
      await route.fulfill({
        json: {
          success: true,
          data: rentalGets === 1 ? rental() : refreshedRental,
        },
      })
      return
    }
    await route.fulfill({ status: 500, json: { success: false, error: 'unexpected mocked API' } })
  })
  await page.route('**/web/**', async route => {
    const url = new URL(route.request().url())
    if (url.pathname === '/web/rentals/42' && route.request().method() === 'PUT') {
      await route.fulfill({ json: { success: true, data: {} } })
      return
    }
    await route.fulfill({ status: 500, json: { success: false, error: 'unexpected mocked web API' } })
  })

  await page.goto('/mobile/gantt')
  await page.goto('/mobile/edit-rental/42')
  await expect(page.getByTestId('save-rental')).toBeVisible()
}

test.describe('mobile edit save confirmation popup', () => {
  test('edit save reloads persisted rental, copies five lines, stays open, then returns on close', async ({ page }) => {
    await page.addInitScript(() => {
      Object.defineProperty(navigator, 'clipboard', {
        configurable: true,
        value: {
          writeText: async (text: string) => {
            ;(window as typeof window & { __copiedText?: string }).__copiedText = text
          },
        },
      })
    })
    await mockEditSave(page)

    await page.getByTestId('save-rental').click()

    const popup = page.getByTestId('rental-confirmation-popup')
    const confirmationText = page.getByTestId('rental-confirmation-text')
    await expect(popup).toBeVisible()
    const text = await confirmationText.innerText()
    expect(text.split('\n')).toHaveLength(5)
    expect(text).toContain('收货地址：重查地址，广东省深圳市南山区，13800138000')

    await page.getByTestId('copy-rental-confirmation').click()
    await expect(page.locator('.van-toast__text')).toHaveText('确认信息已复制')
    await expect(popup).toBeVisible()
    expect(await page.evaluate(() => (window as typeof window & { __copiedText?: string }).__copiedText)).toBe(text)
    await expect(page).toHaveURL(/\/mobile\/edit-rental\/42$/)

    await page.getByTestId('close-rental-confirmation').click()
    await expect(page).toHaveURL(/\/mobile\/gantt$/)
  })

  test('Clipboard rejection falls back to textarea copy and keeps popup open', async ({ page }) => {
    await page.addInitScript(() => {
      Object.defineProperty(navigator, 'clipboard', {
        configurable: true,
        value: { writeText: async () => { throw new Error('denied') } },
      })
      Object.defineProperty(document, 'execCommand', {
        configurable: true,
        value: (command: string) => {
          ;(window as typeof window & { __execCommand?: string }).__execCommand = command
          return true
        },
      })
    })
    await mockEditSave(page)
    await page.getByTestId('save-rental').click()

    await page.getByTestId('copy-rental-confirmation').click()

    await expect(page.locator('.van-toast__text')).toHaveText('确认信息已复制')
    expect(await page.evaluate(() => (window as typeof window & { __execCommand?: string }).__execCommand)).toBe('copy')
    await expect(page.getByTestId('rental-confirmation-popup')).toBeVisible()
  })

  test('both copy methods failing shows fixed manual-copy Toast and keeps popup open', async ({ page }) => {
    await page.addInitScript(() => {
      Object.defineProperty(navigator, 'clipboard', { configurable: true, value: undefined })
      Object.defineProperty(document, 'execCommand', {
        configurable: true,
        value: () => false,
      })
    })
    await mockEditSave(page)
    await page.getByTestId('save-rental').click()

    await page.getByTestId('copy-rental-confirmation').click()

    await expect(page.locator('.van-toast__text')).toHaveText('自动复制失败，请手动选择文本复制')
    await expect(page.getByTestId('rental-confirmation-popup')).toBeVisible()
  })

  test('edit save lookup failure shows fixed Toast and returns', async ({ page }) => {
    await mockEditSave(page, { refreshedRental: null })

    await page.getByTestId('save-rental').click()

    await expect(page.locator('.van-toast__text')).toHaveText('保存成功，但确认信息加载失败')
    await expect(page).toHaveURL(/\/mobile\/gantt$/)
  })

  test('edit failure Toast does not navigate back again after user leaves early', async ({ page }) => {
    await mockEditSave(page, { refreshedRental: null })

    await page.getByTestId('save-rental').click()
    await expect(page.locator('.van-toast__text')).toHaveText('保存成功，但确认信息加载失败')

    await page.locator('.van-nav-bar__left').click()
    await expect(page).toHaveURL(/\/mobile\/gantt$/)
    await expect(page.locator('.van-toast__text')).toBeHidden({ timeout: 5_000 })

    await expect(page).toHaveURL(/\/mobile\/gantt$/)
  })
})

const mockCreateSave = async (
  page: Page,
  options: {
    createResponse?: unknown
    lookup?: 'success' | 'null' | 'reject'
  } = {},
) => {
  const device = {
    id: 8,
    name: '3618',
    serial_number: 'SN-PRIVATE',
    model: 'x300u',
    model_id: 3,
    is_accessory: false,
    status: 'online',
    lifecycle_status: 'active',
    created_at: '2026-01-01',
    updated_at: '2026-01-01',
  }
  const confirmationIds: number[] = []

  await page.route('**/api/**', async route => {
    const request = route.request()
    const url = new URL(request.url())
    if (url.pathname === '/api/gantt/data') {
      await route.fulfill({ json: { success: true, data: { devices: [device], rentals: [] } } })
      return
    }
    if (url.pathname === '/api/device-models') {
      await route.fulfill({
        json: {
          success: true,
          data: [{
            id: 3,
            name: 'x300u',
            display_name: 'VIVO X300 Ultra',
            is_active: true,
            created_at: '2026-01-01',
            updated_at: '2026-01-01',
            accessories: [],
          }],
        },
      })
      return
    }
    if (url.pathname === '/api/devices') {
      await route.fulfill({ json: { devices: [] } })
      return
    }
    if (url.pathname === '/api/rentals/find-slot') {
      await route.fulfill({
        json: {
          success: true,
          data: {
            device,
            available_devices: [device],
            ship_out_date: '2026-07-11',
            ship_in_date: '2026-07-18',
          },
        },
      })
      return
    }
    if (url.pathname === '/api/rentals/check-duplicate') {
      await route.fulfill({
        json: { success: true, data: { has_duplicate: false, duplicates: [] } },
      })
      return
    }
    if (url.pathname === '/api/rentals' && request.method() === 'POST') {
      await route.fulfill({
        json: options.createResponse ?? { success: true, data: { main_rental: { id: 77 } } },
      })
      return
    }
    const match = url.pathname.match(/^\/api\/rentals\/(\d+)$/)
    if (match && request.method() === 'GET') {
      confirmationIds.push(Number(match[1]))
      if (options.lookup === 'reject') {
        await route.abort('failed')
        return
      }
      await route.fulfill({
        json: {
          success: true,
          data: options.lookup === 'null'
            ? null
            : rental({ id: Number(match[1]), destination: '新建重查地址，广东省珠海市香洲区' }),
        },
      })
      return
    }
    await route.fulfill({ status: 500, json: { success: false, error: 'unexpected mocked API' } })
  })

  await page.goto('/mobile/gantt')
  await page.goto('/mobile/create-rental')
  await expect(page.getByTestId('create-rental')).toBeVisible()

  await page.locator('.van-field').filter({ hasText: '客户姓名' }).locator('input').fill('测试客户')
  await page.locator('.van-field').filter({ hasText: '客户电话' }).locator('input').fill('13800138000')
  await page.locator('.van-field').filter({ hasText: '收货地址' }).locator('textarea').fill('表单地址不得用于确认')

  const confirmPicker = async (title: string) => {
    const popup = page.locator('.van-popup--bottom').filter({
      has: page.locator('.van-picker__title', { hasText: title }),
    })
    await expect(popup).toBeVisible()
    await popup.locator('.van-picker__confirm').click()
    await expect(popup).toBeHidden()
  }

  await page.locator('.van-field').filter({ hasText: '设备型号' }).click()
  await confirmPicker('设备型号')
  await page.locator('.van-field').filter({ hasText: '起租日' }).click()
  await confirmPicker('起租日')
  await page.locator('.van-field').filter({ hasText: '还租日' }).click()
  await confirmPicker('还租日')

  const deviceField = page.locator('.van-field').filter({ hasText: '可用设备' })
  await expect(deviceField).not.toHaveAttribute('aria-disabled', 'true')
  await deviceField.click()
  await confirmPicker('可用设备')

  return confirmationIds
}

test.describe('mobile create save confirmation popup', () => {
  test('create extracts data.main_rental.id, reloads it, and never uses form values', async ({ page }) => {
    const confirmationIds = await mockCreateSave(page)

    await page.getByTestId('create-rental').click()

    await expect(page.getByTestId('rental-confirmation-popup')).toBeVisible()
    await expect(page.getByTestId('rental-confirmation-text')).toContainText('新建重查地址')
    await expect(page.getByTestId('rental-confirmation-text')).not.toContainText('表单地址不得用于确认')
    expect(confirmationIds).toEqual([77])
    await expect(page).toHaveURL(/\/mobile\/create-rental$/)

    await page.getByTestId('close-rental-confirmation').click()
    await expect(page).toHaveURL(/\/mobile\/gantt$/)
  })

  test('create response without a numeric ID shows fixed Toast and returns without lookup', async ({ page }) => {
    const confirmationIds = await mockCreateSave(page, {
      createResponse: { success: true, data: { main_rental: {} } },
    })

    await page.getByTestId('create-rental').click()

    await expect(page.locator('.van-toast__text')).toHaveText('保存成功，但确认信息加载失败')
    await expect(page).toHaveURL(/\/mobile\/gantt$/)
    expect(confirmationIds).toEqual([])
  })

  test('create lookup returning null shows fixed Toast and returns', async ({ page }) => {
    await mockCreateSave(page, { lookup: 'null' })

    await page.getByTestId('create-rental').click()

    await expect(page.locator('.van-toast__text')).toHaveText('保存成功，但确认信息加载失败')
    await expect(page).toHaveURL(/\/mobile\/gantt$/)
  })

  test('create lookup rejection shows fixed Toast and returns', async ({ page }) => {
    await mockCreateSave(page, { lookup: 'reject' })

    await page.getByTestId('create-rental').click()

    await expect(page.locator('.van-toast__text')).toHaveText('保存成功，但确认信息加载失败')
    await expect(page).toHaveURL(/\/mobile\/gantt$/)
  })
})
