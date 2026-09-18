import { defineConfig } from '@playwright/test'

import { baseConfig } from './playwright.config'


export const mockTestMatch = [
  '**/batch-shipping-relay.spec.ts',
  '**/edit-rental-damage-note.spec.ts',
  '**/relay-management.spec.ts',
  '**/rental-confirmation.spec.ts',
]

export default defineConfig(baseConfig, {
  testMatch: mockTestMatch,
  webServer: {
    command: 'npm run dev -- --host 127.0.0.1',
    url: 'http://127.0.0.1:5003/mobile/',
    reuseExistingServer: false,
  },
})
