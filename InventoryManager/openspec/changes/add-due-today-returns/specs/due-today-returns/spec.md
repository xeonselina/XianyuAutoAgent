## ADDED Requirements

### Requirement: Identify rentals due for return today

The system MUST identify main rentals whose end date plus one calendar day equals the server's current local date and whose status is `shipped`.

#### Scenario: Shipped main rental ended yesterday
- **WHEN** a main rental has `end_date = today - 1 day` and `status = shipped`
- **THEN** the system SHALL include it in the due-today list

#### Scenario: Rental has a different date or status
- **WHEN** a rental did not end yesterday or its status is not `shipped`
- **THEN** the system SHALL NOT include it

#### Scenario: Accessory child rental matches
- **WHEN** an accessory child rental otherwise matches the date and status
- **THEN** the system SHALL NOT include it as a separate reminder

### Requirement: Display due-today rentals from the Gantt view

The system MUST provide a “今日应归还” button at the top of the desktop Gantt view and display the current count.

#### Scenario: User opens the list
- **WHEN** the user clicks “今日应归还”
- **THEN** a drawer SHALL show phone model, rental date range, destination, phone, and a row action for every matching rental

#### Scenario: No rentals are due
- **WHEN** the due-today result is empty
- **THEN** the drawer SHALL display “今天暂无应归还订单”

### Requirement: Mark a due rental as returned

The system MUST let the user mark each listed rental as `returned` with one row-level action.

#### Scenario: Status update succeeds
- **WHEN** the user clicks “标记为已寄回” and the update succeeds
- **THEN** the rental SHALL disappear from the list, the count SHALL decrease, and the Gantt data SHALL refresh

#### Scenario: Status update fails
- **WHEN** the status request fails
- **THEN** the rental SHALL remain listed, the row action SHALL become available again, and the user SHALL see an error

### Requirement: Use one returned-state label

The system MUST display the `returned` rental status as “已寄回” in desktop and mobile user interfaces while retaining `returned` as the stored value.

#### Scenario: Returned status is rendered
- **WHEN** any desktop or mobile interface renders a rental whose status is `returned`
- **THEN** the visible label SHALL be “已寄回”
