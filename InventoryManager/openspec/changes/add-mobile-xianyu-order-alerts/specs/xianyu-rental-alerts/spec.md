## ADDED Requirements

### Requirement: Mobile Gantt rental-status reminders

The mobile Gantt view MUST display separate, expandable reminders for closed orders and orders requiring refund review, with the linked rentals, their warehouse, status and dates. It MUST offer an action appropriate to each rental status.

#### Scenario: A closed order retains an unshipped rental
- **WHEN** the alert snapshot includes an unshipped or scheduled rental for a closed order
- **THEN** the mobile view SHALL offer a delete action for that rental

#### Scenario: An order requires refund review or a rental was shipped
- **WHEN** an alert requires refund review or its rental is shipped
- **THEN** the mobile view SHALL offer review in the existing rental editor and SHALL NOT offer direct deletion from the reminder

### Requirement: Safe mobile resolution of rental reminders

Before deleting a rental from a mobile reminder, the system MUST re-read the rental and confirm its shop, order, status and warehouse, then ask the user to confirm deletion with the customer, device, dates and linked-accessory effect. Resolution MUST refresh the warning without waiting for the next scheduled check.

#### Scenario: User confirms deletion
- **WHEN** the rental still matches the alert and the user confirms deletion
- **THEN** the existing deletion flow SHALL remove the rental and the mobile view SHALL reload the warning

#### Scenario: Rental changed before action
- **WHEN** the rental no longer matches the alert identity, eligible status or warehouse
- **THEN** the system SHALL stop the action and prompt the user to refresh the reminder

#### Scenario: User ignores a rental reminder
- **WHEN** the user provides a non-empty reason of at most 500 characters and confirms permanent ignore
- **THEN** the system SHALL call the existing rental-ignore API, keep the rental, and remove the reminder
