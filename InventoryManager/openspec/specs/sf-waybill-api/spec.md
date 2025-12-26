# sf-waybill-api Specification

## Purpose
TBD - created by archiving change batch-print-sf-waybills. Update Purpose after archive.
## Requirements
### Requirement: Retrieve waybill PDF from SF Express
The system SHALL call SF Express `COM_RECE_CLOUD_PRINT_WAYBILLS` API to obtain waybill PDF for a rental order.

#### Scenario: Successfully retrieve waybill PDF
**GIVEN** a rental with valid tracking number "SF1234567890"
**AND** SF Express API credentials are configured
**WHEN** get_waybill_pdf() is called
**THEN** the system returns waybill PDF as bytes
**AND** response includes success=True status

#### Scenario: Handle missing tracking number
**GIVEN** a rental without tracking number
**WHEN** get_waybill_pdf() is called
**THEN** the system returns success=False
**AND** error message "缺少运单号"

#### Scenario: Handle SF API error
**GIVEN** SF Express API returns error code "ERR_001"
**WHEN** get_waybill_pdf() is called
**THEN** the system logs the error
**AND** returns success=False with SF error message
**AND** does not raise exception

### Requirement: Construct SF API request with rental details
The system SHALL include all required rental information in the SF API request.

#### Scenario: Include order details in API request
**GIVEN** rental with ID 123 and tracking number "SF1234567890"
**WHEN** constructing SF API request
**THEN** request includes orderId field
**AND** request includes tracking number
**AND** request includes receiver contact information
**AND** request includes sender contact information

### Requirement: Handle API authentication
The system SHALL use existing msgDigest authentication method for SF API calls.

#### Scenario: Generate valid authentication signature
**GIVEN** SF API credentials (partner_id, checkword)
**WHEN** making API request
**THEN** request includes valid msgDigest signature
**AND** request includes timestamp
**AND** request includes requestID

### Requirement: Support API retry on transient failures
The system SHALL retry SF API calls up to 2 times on network errors.

#### Scenario: Retry on timeout error
**GIVEN** first SF API call times out
**WHEN** get_waybill_pdf() is executed
**THEN** the system retries the request
**AND** waits 1 second before retry
**AND** maximum 2 retries are attempted

#### Scenario: No retry on business logic error
**GIVEN** SF API returns error "运单号不存在"
**WHEN** get_waybill_pdf() is executed
**THEN** the system does NOT retry
**AND** returns error immediately

