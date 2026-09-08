## ADDED Requirements

### Requirement: Verify platform status for recorded rentals
The system SHALL check actual Xianyu status for orders linked to unshipped, scheduled or shipped rentals, scoped by shop and order number. Rental count SHALL NOT imply cancellation. Returned, completed and cancelled history SHALL NOT trigger alerts.

#### Scenario: A valid order books two devices
- **WHEN** two rentals share an active order with no refund
- **THEN** neither rental triggers a refund or closure alert

#### Scenario: A closed order has multiple rentals
- **WHEN** Xianyu reports order status 23 or 24
- **THEN** one alert lists all remaining active rentals for that shop and order regardless of amount or date

#### Scenario: A refund does not close the order
- **WHEN** refund status is 1, 2, 3, 5 or 8 but the order remains active
- **THEN** the system asks the user to review fulfillment and does not suggest deleting the whole order

### Requirement: Persistent inline reminders
The system SHALL reuse the missing-order alert interaction with collapsed inline details, distinct closure and refund-review groups, and a confirmation identifying the customer, device and dates before deleting a rental. Shipped rentals SHALL display a return/recovery reminder and open the existing editor for review.

#### Scenario: One of two rentals is deleted
- **WHEN** the user confirms deletion of one rental
- **THEN** the alert immediately retains only the remaining rental and disappears after all active rentals are handled

### Requirement: Trustworthy cached status
The system SHALL verify orders absent from the waiting-to-ship list through order detail, preserve prior reminders on failures, and isolate reminders from permanent missing-order ignores.

#### Scenario: One detail request fails
- **WHEN** a detail response is missing, malformed or belongs to a different order
- **THEN** the old reminder for that order remains, a failure message is shown, and other verified orders still update

#### Scenario: Rental identity changes
- **WHEN** a rental is deleted, completed, cancelled or linked to a different order/shop
- **THEN** cached reminders for the original identity no longer list that rental
