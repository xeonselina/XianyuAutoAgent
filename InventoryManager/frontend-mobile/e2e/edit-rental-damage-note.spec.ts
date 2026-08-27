import { expect, test } from '@playwright/test'

import { mockAuthenticatedMobileSession } from './helpers/mock-auth'


test.describe('Edit Rental — damage note', () => {
  test('loads and submits the current customer damage report', async ({ page }) => {
    await mockAuthenticatedMobileSession(page)

    const rental = {
      id: 77,
      device_id: 9,
      warehouse_id: 1,
      device: {
        id: 9,
        name: '2001',
        serial_number: 'SN-2001',
        model: 'x200u',
      },
      start_date: '2026-08-01',
      end_date: '2026-08-05',
      customer_name: '测试客户',
      customer_phone: '13800138000',
      destination: '测试地址',
      status: 'returned',
      includes_handle: false,
      includes_lens_mount: false,
      photo_transfer: false,
      accessories: [],
      damage_note: '屏幕右下角碎裂',
    }
    let updateBody: Record<string, unknown> | null = null

    await page.route('**/api/gantt/data**', route => route.fulfill({
      json: { success: true, data: { devices: [rental.device], rentals: [rental] } },
    }))
    await page.route('**/api/devices**', route => route.fulfill({
      json: { devices: [] },
    }))
    await page.route('**/api/rentals/77', route => route.fulfill({
      json: { success: true, data: rental },
    }))
    await page.route('**/web/rentals/77', async route => {
      updateBody = route.request().postDataJSON()
      await route.fulfill({ json: { success: true, data: { id: 77 } } })
    })

    await page.goto('/mobile/edit-rental/77')

    const damageField = page.getByTestId('damage-note').locator('textarea')
    await expect(damageField).toHaveValue('屏幕右下角碎裂')
    await expect(page.getByTestId('damage-note-warning')).toContainText('已记录用户损坏反馈')

    await damageField.fill('镜头卡口松动')
    await page.getByTestId('save-rental').click()

    await expect.poll(() => updateBody?.damage_note).toBe('镜头卡口松动')
  })
})
