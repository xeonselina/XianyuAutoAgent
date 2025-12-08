# Batch Shipping Capability

## ADDED Requirements

### Requirement: Batch Shipping Page

The system SHALL provide a dedicated batch shipping page for managing the complete shipping workflow from order preview to scheduled shipment.

#### Scenario: Access batch shipping page

- **WHEN** user clicks "批量发货" button in Gantt chart
- **THEN** system navigates to `/batch-shipping` route displaying the batch shipping page

#### Scenario: Select date range

- **WHEN** user selects start and end dates
- **AND** clicks "预览订单" button
- **THEN** system fetches rentals with `ship_out_time` in date range
- **AND** displays them in a table with columns: rental ID, customer, device, status, waybill

#### Scenario: Display order status

- **WHEN** batch shipping page loads rental data
- **THEN** each rental displays one of these status badges:
  - "未打印" if no print record
  - "已打印" if printed but no waybill
  - "已录入运单" if `sf_waybill_no` exists
  - "已发货" if `status = 'shipped'`

#### Scenario: No orders in date range

- **WHEN** user previews orders for a date range with no rentals
- **THEN** system displays message "该日期范围内未找到发货单"
- **AND** disables batch print and schedule buttons

### Requirement: Batch Print Navigation

The system SHALL allow users to navigate from batch shipping page to batch print view.

#### Scenario: Print all orders

- **WHEN** user clicks "批量打印发货单" button
- **THEN** system navigates to `/batch-shipping-order` route
- **AND** passes date range as query parameters
- **AND** batch print view displays all orders with QR codes

### Requirement: Schedule Shipping

The system SHALL allow users to schedule batch shipment for a future time.

#### Scenario: Schedule future shipment

- **WHEN** user clicks "预约发货" button
- **AND** inputs scheduled time (default: now + 1 hour)
- **AND** confirms schedule
- **THEN** system updates `scheduled_ship_time` for all rentals with `sf_waybill_no`
- **AND** displays confirmation message with count of scheduled rentals

#### Scenario: Schedule disabled without waybills

- **WHEN** no rentals in current list have `sf_waybill_no` recorded
- **THEN** "预约发货" button is disabled
- **AND** tooltip shows "请先录入运单号"

#### Scenario: Schedule only valid rentals

- **WHEN** user schedules shipment for 5 rentals
- **AND** only 3 have waybill numbers recorded
- **THEN** system schedules only the 3 valid rentals
- **AND** displays warning "仅预约了 3 个订单(另 2 个缺少运单号)"

### Requirement: Scheduled Shipment Execution

The system SHALL automatically execute scheduled shipments at the appointed time via background task.

#### Scenario: Execute scheduled shipment

- **WHEN** current time >= rental's `scheduled_ship_time`
- **AND** rental has `sf_waybill_no` and `status != 'shipped'`
- **THEN** system calls SF Express API to create shipping order
- **AND** calls Xianyu API to notify shipment (if `xianyu_order_no` exists)
- **AND** updates rental `status = 'shipped'` and `ship_out_time = current_time`

#### Scenario: Handle API failure during scheduled shipment

- **WHEN** SF Express or Xianyu API call fails
- **THEN** system logs error with rental ID and error message
- **AND** retries up to 3 times with exponential backoff
- **AND** if all retries fail, marks rental for manual intervention
- **AND** sends alert notification to administrators

#### Scenario: Skip already shipped rentals

- **WHEN** scheduled task processes a rental with `status = 'shipped'`
- **THEN** system skips the rental without calling APIs
- **AND** logs "Rental already shipped, skipping"
