## ADDED Requirements

### Requirement: Identify missing inventory reservations

The system MUST identify every Xianyu order from the configured store whose order status is waiting for shipment, whose paid amount is strictly greater than 5000 cents, and whose order number is absent from inventory rentals and permanent ignores.

#### Scenario: Eligible order is missing
- **WHEN** an order has `order_status = 12`, `pay_amount > 5000`, and no matching `rentals.xianyu_order_no`
- **THEN** the system SHALL create or update a pending missing-order alert

#### Scenario: Amount is exactly fifty yuan
- **WHEN** an order has `pay_amount = 5000`
- **THEN** the system SHALL NOT create an alert

#### Scenario: Refund state differs
- **WHEN** two otherwise eligible orders have different refund states
- **THEN** refund state SHALL NOT affect eligibility

### Requirement: Reconcile orders reliably

The system MUST reconcile all pages of waiting-for-shipment orders every ten minutes, on Gantt entry, and on manual refresh without running duplicate external queries concurrently.

#### Scenario: Complete reconciliation succeeds
- **WHEN** every requested order-list page succeeds
- **THEN** the system SHALL atomically update pending alerts and the last-success timestamp

#### Scenario: One page fails
- **WHEN** any requested order-list page fails
- **THEN** the system SHALL retain the previous alert cache and record the failure

#### Scenario: Refresh overlaps
- **WHEN** a scheduled or user-triggered reconciliation is already running
- **THEN** another refresh SHALL reuse the current state without starting a second external query

### Requirement: Display alerts in the Gantt view

The system MUST display missing-order warnings only as an inline warning area at the top of the existing Gantt view.

#### Scenario: Pending alerts exist
- **WHEN** the user opens the Gantt view and pending alerts exist
- **THEN** the warning area SHALL show the count and allow inline expansion of buyer nickname, mobile, paid amount, order time, goods, and order number

#### Scenario: Last refresh failed
- **WHEN** the most recent reconciliation failed
- **THEN** the warning area SHALL retain prior alerts and show the last successful check time and failure state

### Requirement: Reuse the existing booking dialog

The system MUST use the existing `BookingDialog` for missing-order entry.

#### Scenario: User starts entry
- **WHEN** the user chooses “去补录” for an alert
- **THEN** the system SHALL open the existing dialog, seed the order number, invoke the existing order-detail fetch flow, and leave dates, device, model, and accessories for the user to complete

#### Scenario: Entry succeeds
- **WHEN** a rental with the alert order number is created successfully
- **THEN** the alert SHALL disappear without waiting for the next scheduled external reconciliation

### Requirement: Permanently ignore an order

The system MUST allow a user to permanently ignore an order after providing a reason and confirming that the action cannot be restored.

#### Scenario: Ignore is confirmed
- **WHEN** the user supplies a non-empty reason and confirms permanent ignore
- **THEN** the order SHALL immediately disappear and SHALL NOT alert again

#### Scenario: Ignore lacks a reason
- **WHEN** the ignore reason is empty
- **THEN** the system SHALL reject the operation and retain the alert

