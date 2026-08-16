import { expect, test } from '@playwright/test'


const baseRental = {
  device_id: 1,
  start_date: '2026-08-21',
  end_date: '2026-08-24',
  ship_out_time: '2026-08-20T19:00:00',
  customer_phone: '13800138000',
  destination: '上海市浦东新区',
  status: 'not_shipped',
  ship_out_tracking_no: null,
  includes_handle: false,
  includes_lens_mount: false,
  photo_transfer: false,
  device: { id: 1, name: 'X300U-01', model: 'x300u' },
}


test('relay rentals are marked and excluded from mobile multi-select', async ({ page }) => {
  await page.route('**/api/rentals/by-ship-date**', async route => {
    await route.fulfill({
      json: {
        success: true,
        data: {
          rentals: [
            {
              ...baseRental,
              id: 101,
              customer_name: '普通订单',
              is_relay_shipping: false,
              relay_predecessor_rental_id: null,
            },
            {
              ...baseRental,
              id: 102,
              customer_name: '接力订单',
              is_relay_shipping: true,
              relay_predecessor_rental_id: 100,
            },
          ],
        },
      },
    })
  })

  await page.goto('/mobile/batch-shipping')

  const relayCard = page.locator('[data-testid="batch-shipping-card"][data-rental-id="102"]')
  await expect(relayCard.getByTestId('relay-shipping-tag')).toHaveText('接力寄出')
  await expect(relayCard.locator('.van-checkbox')).toHaveClass(/van-checkbox--disabled/)
  await expect(relayCard).toHaveAttribute('title', /不能批量发货/)

  await page.getByRole('button', { name: '全选' }).click()
  await expect(page.getByRole('button', { name: '预约发货 (1)' })).toBeVisible()
  await expect(relayCard).not.toHaveClass(/checked/)

  await relayCard.locator('.card-body').click()
  await expect(page.getByText('接力订单由前一位客户直接寄出，不能批量发货')).toBeVisible()
})
