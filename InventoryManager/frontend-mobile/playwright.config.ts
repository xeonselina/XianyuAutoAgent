import { defineConfig, devices } from '@playwright/test'

const noProxy = new Set(
  (process.env.NO_PROXY ?? '').split(',').filter(Boolean),
)
noProxy.add('127.0.0.1')
noProxy.add('localhost')
process.env.NO_PROXY = [...noProxy].join(',')

export const baseConfig = defineConfig({
  testDir: './e2e',
  outputDir: process.env.E2E_OUTPUT_DIR ?? 'test-results',
  timeout: 30_000,
  retries: 0,
  reporter: [['list']],

  use: {
    // Mobile viewport (iPhone 13)
    ...devices['iPhone 13'],
    baseURL: 'http://127.0.0.1:5003',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },

  projects: [
    {
      name: 'mobile-chromium',
      use: {
        ...devices['iPhone 13'],
        browserName: 'chromium',   // override iPhone 13's defaultBrowserType:'webkit'
        baseURL: 'http://127.0.0.1:5003',
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

export default baseConfig
