# Capability: Kuaimai Cloud Printing Integration

## Summary
Integrate Kuaimai (快麦) cloud printing service to send waybill images to thermal printers.

## ADDED Requirements

### Requirement: Authenticate with Kuaimai API
The system SHALL generate valid MD5 signatures for Kuaimai API requests.

#### Scenario: Generate valid signature
**GIVEN** appId "1100", appSecret "secret123", and timestamp "2024-01-15 10:00:00"
**WHEN** _generate_sign() is called with parameters
**THEN** the system sorts parameters by key ASCII order
**AND** constructs string: appSecret + sorted_params + appSecret
**AND** returns 32-character lowercase MD5 hash

#### Scenario: Include signature in API request
**GIVEN** API parameters with generated signature
**WHEN** making Kuaimai API call
**THEN** request includes appId parameter
**AND** request includes timestamp parameter
**AND** request includes sign parameter
**AND** Content-Type header is application/json

### Requirement: Send print job to Kuaimai printer
The system SHALL submit base64 encoded images to Kuaimai printer using tsplXmlWrite API.

#### Scenario: Successfully submit print job
**GIVEN** printer_id "printer_001" and base64 image data
**WHEN** print_image() is called
**THEN** the system sends POST request to cloud.kuaimai.com/api
**AND** request body includes printer_id
**AND** request body includes base64 image data
**AND** request body includes copies=1
**AND** returns job_id on success

#### Scenario: Handle printer offline
**GIVEN** printer is offline
**WHEN** print_image() is called
**THEN** Kuaimai API returns error "打印机离线"
**AND** system returns success=False
**AND** error message is passed to caller

#### Scenario: Handle invalid printer ID
**GIVEN** non-existent printer_id "invalid_printer"
**WHEN** print_image() is called
**THEN** Kuaimai API returns error
**AND** system returns success=False with error message

### Requirement: List available printers
The system SHALL retrieve list of printers associated with the account.

#### Scenario: Fetch printer list
**GIVEN** valid Kuaimai credentials
**WHEN** list_printers() is called
**THEN** the system returns list of printer objects
**AND** each printer includes id field
**AND** each printer includes name field
**AND** each printer includes status field

#### Scenario: Cache printer list
**GIVEN** printer list was fetched 3 minutes ago
**WHEN** list_printers() is called again
**THEN** the system returns cached list
**AND** does not make new API call

#### Scenario: Refresh cache after expiration
**GIVEN** printer list cache is 6 minutes old
**WHEN** list_printers() is called
**THEN** the system makes new API call
**AND** updates cache with fresh data

### Requirement: Track print job status
The system SHALL query Kuaimai API for print job status.

#### Scenario: Check completed print job
**GIVEN** job_id "job_12345" for completed print
**WHEN** get_print_status(job_id) is called
**THEN** the system returns status "completed"
**AND** includes completion timestamp

#### Scenario: Check failed print job
**GIVEN** job_id "job_67890" for failed print
**WHEN** get_print_status(job_id) is called
**THEN** the system returns status "failed"
**AND** includes failure reason

### Requirement: Handle API rate limiting
The system SHALL respect Kuaimai API rate limits and retry with backoff.

#### Scenario: Handle rate limit error
**GIVEN** Kuaimai API returns rate limit error (code 429)
**WHEN** making API request
**THEN** the system waits 2 seconds
**AND** retries request once
**AND** returns error if retry also fails

### Requirement: Validate configuration on initialization
The system SHALL verify Kuaimai credentials are configured before use.

#### Scenario: Missing appId configuration
**GIVEN** KUAIMAI_APP_ID environment variable is not set
**WHEN** KuaimaiPrintService is initialized
**THEN** the system logs warning message
**AND** service is created but marked as unconfigured

#### Scenario: API call with missing credentials
**GIVEN** KuaimaiPrintService is unconfigured
**WHEN** print_image() is called
**THEN** the system returns error immediately
**AND** error message indicates missing configuration
**AND** does not attempt API call
