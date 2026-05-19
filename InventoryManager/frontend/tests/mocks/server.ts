import { setupServer } from 'msw/node'
import { handlers } from './handlers'

/**
 * MSW Server Setup
 * 
 * Sets up the MSW server with all request handlers
 * This should be used in test setup to intercept API calls
 */
export const server = setupServer(...handlers)
