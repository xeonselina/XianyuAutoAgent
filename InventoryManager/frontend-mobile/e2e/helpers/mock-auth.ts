import type { Page } from '@playwright/test'
import type { MobileSession } from '../../src/stores/auth'
import type { MobileWarehouse } from '../../src/stores/tenant'


const session = {
  csrf_token: 'mobile-e2e-csrf',
  member: {
    id: 1,
    phone: '13800138000',
    role: 'admin',
    status: 'active',
  },
  tenant: {
    id: 1,
    name: '移动端 E2E 租户',
    access_status: 'active',
  },
} satisfies MobileSession

const warehouses = [{
  id: 1,
  province: '广东省',
  city: '广州市',
  name: '移动端 E2E 仓库',
}] satisfies MobileWarehouse[]

export async function mockAuthenticatedMobileSession(page: Page) {
  await page.route('**/auth/me', async route => {
    await route.fulfill({
      json: {
        success: true,
        data: session,
      },
    })
  })
  await page.route('**/api/warehouses', async route => {
    await route.fulfill({
      json: {
        success: true,
        data: warehouses,
      },
    })
  })
}
