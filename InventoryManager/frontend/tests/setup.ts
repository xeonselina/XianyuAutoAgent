import { beforeAll, afterEach, afterAll } from 'vitest'
import { server } from './mocks/server'
import { resetMockData } from './mocks/handlers'

/**
 * Global test setup for MSW and API mocking
 */

// Start MSW server before all tests
beforeAll(() => {
  server.listen({ onUnhandledRequest: 'error' })
})

// Reset mock data between each test to prevent state bleed
afterEach(() => {
  resetMockData()
  server.resetHandlers()
})

// Cleanup after all tests
afterAll(() => {
  server.close()
})
