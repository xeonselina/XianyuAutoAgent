## ADDED Requirements

### Requirement: Enable multi-selection for batch shipping
The system SHALL allow users to select specific rental orders for batch shipping instead of requiring all unshipped orders to be scheduled at once.

#### Scenario: Display selection checkboxes for unshipped orders
**GIVEN** user views batch shipping page
**AND** there are 5 unshipped rental orders
**WHEN** the orders table loads
**THEN** each row shows a checkbox in the selection column
**AND** only orders with status `not_shipped` are selectable
**AND** orders with status `shipped` or `scheduled_for_shipping` have disabled checkboxes

#### Scenario: Update scheduled shipment button based on selection
**GIVEN** user has selected 3 rental orders
**WHEN** the selection changes
**THEN** the "预约发货" button shows text "预约发货 (3)"
**AND** the button is enabled

#### Scenario: Disable scheduled shipment button when no selection
**GIVEN** user has not selected any rental orders
**WHEN** the page loads or all selections are cleared
**THEN** the "预约发货" button shows text "预约发货 (0)"
**AND** the button is disabled

#### Scenario: Schedule only selected orders
**GIVEN** user has selected rental IDs [101, 102, 105]
**WHEN** user clicks "预约发货" button and confirms
**THEN** API is called with `rental_ids: [101, 102, 105]`
**AND** only the selected 3 orders are scheduled for shipping
**AND** other unselected orders remain in `not_shipped` status

#### Scenario: Preserve selection state during interaction
**GIVEN** user has selected 3 rental orders
**WHEN** user opens and closes the schedule dialog without confirming
**THEN** the 3 orders remain selected in the table
**AND** the button still shows "预约发货 (3)"

### Requirement: Display device previous rental status
The system SHALL show the status of each device's previous rental order to help users identify potential shipping risks.

#### Scenario: Show device available status when previous rental completed
**GIVEN** rental order #105 for device #42
**AND** device #42 has a previous rental #99 with status `completed`
**WHEN** user views batch shipping page
**THEN** rental #105 row shows green tag "✓ 设备在库" in device status column
**AND** user can safely schedule this order for shipping

#### Scenario: Show warning when previous rental not completed
**GIVEN** rental order #106 for device #43
**AND** device #43 has a previous rental #100 with status `shipped`
**WHEN** user views batch shipping page
**THEN** rental #106 row shows red tag "⚠ 上一单未结束" in device status column
**AND** user is warned that device may not be available

#### Scenario: Show dash for first rental of a device
**GIVEN** rental order #107 for device #44
**AND** device #44 has no previous rental orders
**WHEN** user views batch shipping page
**THEN** rental #107 row shows "-" in device status column
**AND** indicates this is the device's first rental

#### Scenario: Consider multiple completion statuses
**GIVEN** rental order #108 for device #45
**AND** device #45 has previous rentals with statuses:
  - Rental #101: `cancelled` (most recent)
  - Rental #100: `shipped` (older)
**WHEN** user views batch shipping page
**THEN** rental #108 row shows green tag "✓ 设备在库"
**AND** system considers `cancelled` as a completed status

#### Scenario: API returns previous rental status for each order
**GIVEN** user requests batch shipping orders for date range
**WHEN** API `/api/rentals/by-ship-date` is called
**THEN** each rental object includes:
  - `has_previous_rental`: boolean
  - `previous_rental_status`: string or null
  - `previous_rental_completed`: boolean or null
**AND** previous rental is determined by same `device_id` with earlier `ship_out_time`

### Requirement: Query previous rental efficiently
The system SHALL retrieve previous rental status for each device without causing performance degradation.

#### Scenario: Query previous rental by device and time
**GIVEN** processing rental order #105 for device #42 shipped on 2025-01-15
**WHEN** system queries for previous rental
**THEN** system executes query:
  - Filter: `device_id = 42`
  - Filter: `ship_out_time < 2025-01-15`
  - Filter: `parent_rental_id IS NULL`
  - Order by: `ship_out_time DESC`
  - Limit: 1
**AND** returns the most recent previous rental

#### Scenario: Handle no previous rental
**GIVEN** rental order is the first rental for this device
**WHEN** system queries for previous rental
**THEN** query returns no results
**AND** API response includes:
  - `has_previous_rental: false`
  - `previous_rental_status: null`
  - `previous_rental_completed: null`

#### Scenario: Determine completion status correctly
**GIVEN** previous rental has status `returned`
**WHEN** system evaluates completion
**THEN** `previous_rental_completed` is `true`
**AND** statuses considered completed are: `completed`, `cancelled`, `returned`
**AND** statuses considered not completed are: `not_shipped`, `scheduled_for_shipping`, `shipped`
