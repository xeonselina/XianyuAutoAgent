import { request as playwrightRequest } from '@playwright/test'
import { mkdir } from 'node:fs/promises'
import path from 'node:path'

import {
  realAuthStatePath,
  realMobileOrigin,
} from '../helpers/real-backend'


export default async function globalSetup() {
  const phone = process.env.E2E_ADMIN_PHONE ?? '13800138000'
  const code = process.env.E2E_SMS_CODE ?? '246810'
  const api = await playwrightRequest.newContext({ baseURL: realMobileOrigin })
  try {
    const requested = await api.post('/auth/sms/request', {
      data: { phone },
    })
    if (!requested.ok()) {
      throw new Error(`E2E SMS request failed with HTTP ${requested.status()}`)
    }

    const verified = await api.post('/auth/sms/verify', {
      data: { phone, code },
    })
    if (!verified.ok()) {
      throw new Error(`E2E SMS verification failed with HTTP ${verified.status()}`)
    }

    await mkdir(path.dirname(realAuthStatePath), { recursive: true })
    await api.storageState({ path: realAuthStatePath })
  } finally {
    await api.dispose()
  }
}
