# Xianyu API Integration Capability

## ADDED Requirements

### Requirement: Xianyu Order Shipment Notification

The system SHALL notify Xianyu platform of order shipments via Xianyu Steward API.

#### Scenario: Notify shipment

- **WHEN** scheduled shipment execution triggers
- **AND** rental has `xianyu_order_no` (not null or empty)
- **THEN** system calls Xianyu `/api/open/order/ship` endpoint
- **AND** includes order_no, waybill_no, express_code, express_name
- **AND** receives success response (code=0)

#### Scenario: Skip rentals without Xianyu order

- **WHEN** rental has no `xianyu_order_no`
- **THEN** system logs "Rental {id} has no Xianyu order, skipping notification"
- **AND** continues with other rentals
- **AND** does not fail the shipment

### Requirement: Xianyu API Authentication

The system SHALL authenticate Xianyu API requests using MD5 signature.

#### Scenario: Generate signature

- **WHEN** calling Xianyu API
- **THEN** system generates signature:
  1. Sort parameters by key alphabetically
  2. Concatenate key-value pairs (no separators)
  3. Append secret key at the end
  4. Calculate MD5 hash
- **AND** includes signature in query parameter `sign`

#### Scenario: Request parameters

- **WHEN** constructing Xianyu shipment request
- **THEN** system includes query parameters:
  - `appid` from config `XIANYU_APP_ID`
  - `timestamp` current Unix timestamp in seconds
  - `seller_id` from config (optional)
  - `sign` generated signature
- **AND** includes JSON body:
  - `order_no` from rental.xianyu_order_no
  - `waybill_no` from rental.sf_waybill_no or ship_out_tracking_no
  - `express_code` = "shunfeng"
  - `express_name` = "顺丰速运"
  - Optional sender info (ship_name, ship_mobile, ship_address)

### Requirement: Xianyu API Error Handling

The system SHALL handle Xianyu API errors gracefully without blocking shipment.

#### Scenario: Xianyu API failure

- **WHEN** Xianyu API returns error (code != 0)
- **THEN** system logs error with order_no, error code, error message
- **AND** continues processing other rentals
- **AND** does not mark rental as failed (SF shipment still succeeds)

#### Scenario: Network timeout

- **WHEN** Xianyu API request times out
- **THEN** system retries once after 2 seconds
- **AND** logs timeout error if retry fails
- **AND** continues processing (non-blocking)

#### Scenario: Invalid order number

- **WHEN** Xianyu API returns "order not found" error
- **THEN** system logs warning "Xianyu order {order_no} not found, may be outdated"
- **AND** marks rental as shipped anyway (local system is source of truth)

### Requirement: Xianyu API Configuration

The system SHALL load Xianyu API credentials from environment variables.

#### Scenario: Load credentials

- **WHEN** application starts
- **THEN** system loads from environment:
  - `XIANYU_APP_ID` - Xianyu AppKey
  - `XIANYU_SECRET` - Xianyu secret for signature
  - `XIANYU_SELLER_ID` - Seller ID (optional)
  - `XIANYU_SHIP_NAME` - Default sender name (optional)
  - `XIANYU_SHIP_MOBILE` - Default sender phone (optional)
  - `XIANYU_SHIP_ADDRESS` - Default sender address (optional)

#### Scenario: Missing credentials

- **WHEN** Xianyu credentials are missing
- **THEN** system logs warning
- **AND** skips Xianyu notification during shipment
- **AND** continues with SF Express shipment only

### Requirement: Xianyu Sender Information

The system SHALL provide sender information in Xianyu shipment notification.

#### Scenario: Use configured sender info

- **WHEN** environment variables have sender info
- **THEN** system includes in Xianyu request:
  - `ship_name` from `XIANYU_SHIP_NAME`
  - `ship_mobile` from `XIANYU_SHIP_MOBILE`
  - `ship_address` from `XIANYU_SHIP_ADDRESS`

#### Scenario: Use default sender from Xianyu backend

- **WHEN** sender info not configured in environment
- **THEN** system omits sender fields from request
- **AND** Xianyu uses default sender address from backend settings

#### Scenario: Address format

- **WHEN** sender address is provided
- **THEN** system splits or provides:
  - Option 1: `ship_district_id` if available
  - Option 2: `ship_prov_name`, `ship_city_name`, `ship_area_name`, `ship_address`
- **AND** uses Option 2 by default (full text address)
