/**
 * Production DB safety guard
 *
 * This test suite runs against the PRODUCTION database.
 * Rules enforced here:
 *  1. All test-created rentals MUST use dates >= TEST_START_DATE (October 2026)
 *  2. Tests MUST NOT DELETE any rental that was NOT created in this test run
 *  3. Tests MAY delete rentals they created (identified by TEST_CUSTOMER_PREFIX + being >= TEST_START_DATE)
 *  4. Tests MUST NOT call PUT/PATCH on rentals not created in this test run
 *  5. Reads (GET) are always safe
 */

export const TEST_START_DATE = '2026-10-01'
export const TEST_END_DATE   = '2026-10-07'

/** Prefix applied to all test-created rental customer names */
export const TEST_CUSTOMER_PREFIX = '【E2E测试】'

/** A rental payload that is safe to POST (future dates, production won't overlap real use) */
export const safeTestRental = {
  customer_name:  `${TEST_CUSTOMER_PREFIX}客户`,
  customer_phone: '13900000001',
  destination:    'E2E测试地址-自动化测试',
  start_date:     TEST_START_DATE,
  end_date:       TEST_END_DATE,
  notes:          '自动化测试租赁单 — 测试结束后将自动删除',
}

/**
 * Assert that a date string is safe for test use (>= October 2026).
 * Throws if the date would overlap real production data.
 */
export function assertSafeDate(date: string): void {
  if (date < TEST_START_DATE) {
    throw new Error(
      `SAFETY: test date "${date}" is before ${TEST_START_DATE}. ` +
      'Use dates >= October 2026 to avoid touching production data.'
    )
  }
}

/**
 * Assert that a rental ID is safe to delete:
 *  - customer_name must start with TEST_CUSTOMER_PREFIX
 *  - start_date must be >= TEST_START_DATE
 */
export function assertSafeToDelete(rental: { customer_name: string; start_date: string; id: number }): void {
  if (!rental.customer_name.startsWith(TEST_CUSTOMER_PREFIX)) {
    throw new Error(
      `SAFETY: refusing to delete rental #${rental.id} — ` +
      `customer_name "${rental.customer_name}" does not start with "${TEST_CUSTOMER_PREFIX}". ` +
      'Only test-created rentals may be deleted.'
    )
  }
  assertSafeDate(rental.start_date)
}
