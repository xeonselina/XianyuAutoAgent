## ADDED Requirements

### Requirement: Mobile Gantt missing-order reminders

The mobile Gantt view MUST display the existing missing-order snapshot as an inline, expandable warning with the pending count, buyer nickname, mobile number, paid amount, order time, goods and order number. It MUST expose the existing synchronization error, stale state and immediate-check action even when no pending order remains.

#### Scenario: A missing order is present
- **WHEN** a user opens the mobile Gantt view and the snapshot contains a pending order
- **THEN** the view SHALL show the warning count and allow the user to expand its order details

#### Scenario: Synchronization is unhealthy with no pending orders
- **WHEN** the snapshot has no pending orders and the last check failed or is stale
- **THEN** the warning SHALL remain visible with the check state and an immediate-check action

#### Scenario: User returns after recording an order
- **WHEN** the user returns to the mobile Gantt view after recording an order
- **THEN** the view SHALL reload the snapshot so the resolved warning disappears without waiting for scheduled reconciliation

### Requirement: Mobile missing-order actions

The mobile warning MUST offer entry through the existing rental creation flow and permanent ignore through the existing alert API.

#### Scenario: User starts order entry
- **WHEN** the user chooses “去补录” or “去补齐”
- **THEN** the existing mobile rental creation view SHALL receive the shop and order number, fetch order details, and leave dates and equipment for the user to complete

#### Scenario: User ignores an order
- **WHEN** the user provides a non-empty reason of at most 500 characters and confirms permanent ignore
- **THEN** the system SHALL call the existing ignore API and immediately remove the resolved warning

#### Scenario: User does not confirm ignore
- **WHEN** the user supplies no valid reason or cancels the confirmation
- **THEN** the warning SHALL remain and no ignore request SHALL be sent
