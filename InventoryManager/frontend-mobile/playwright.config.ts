import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  retries: 1,
  reporter: [['html', { open: 'never' }], ['list']],

  use: {
    // Mobile viewport (iPhone 13)
    ...devices['iPhone 13'],
    baseURL: 'http://localhost:5003',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },

  projects: [
    {
      name: 'mobile-chromium',
      use: {
        ...devices['iPhone 13'],
        browserName: 'chromium',   // override iPhone 13's defaultBrowserType:'webkit'
        baseURL: 'http://localhost:5003',
      }
    }
  ],

  // Assumes the dev server is already running (npm run dev)
  // If you want Playwright to start it automatically, uncomment:
  // webServer: {
  //   command: 'npm run dev',
  //   port: 5003,
  //   reuseExistingServer: true,
  // },
})
