import { defineConfig } from '@playwright/test'

import { baseConfig } from './playwright.config'
import { mockTestMatch } from './playwright.mock.config'
import { realAuthStatePath } from './e2e/helpers/real-backend'


export default defineConfig(baseConfig, {
  globalSetup: './e2e/real/global-setup.ts',
  globalTeardown: './e2e/real/global-teardown.ts',
  testIgnore: mockTestMatch,
  workers: 1,
  use: {
    storageState: realAuthStatePath,
  },
  webServer: [
    {
      command: 'npm --prefix ../frontend run dev -- --host 127.0.0.1',
      env: {
        E2E_BACKEND_TARGET: (
          process.env.E2E_BACKEND_TARGET ?? 'http://localhost:5001'
        ),
      },
      url: 'http://127.0.0.1:5002/login',
      reuseExistingServer: false,
      timeout: 120_000,
    },
    {
      command: 'npm run dev -- --host 127.0.0.1',
      env: {
        E2E_BACKEND_TARGET: (
          process.env.E2E_BACKEND_TARGET ?? 'http://localhost:5001'
        ),
      },
      url: 'http://127.0.0.1:5003/mobile/',
      reuseExistingServer: false,
      timeout: 120_000,
    },
  ],
})
