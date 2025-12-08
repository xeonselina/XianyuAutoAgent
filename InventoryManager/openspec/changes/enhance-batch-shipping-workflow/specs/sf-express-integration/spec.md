# SF Express Integration Capability

## ADDED Requirements

### Requirement: SF Express OAuth2 Authentication

The system SHALL authenticate with SF Express API using OAuth2 client credentials flow.

#### Scenario: Obtain access token

- **WHEN** system needs to call SF Express business API
- **THEN** system generates signature: MD5(`appKey` + `timestamp` + `appSecret`)
- **AND** calls `POST /oauth2/accessToken` with appKey, timestamp, signature
- **AND** receives access token valid for specified duration
- **AND** caches token until expiration

#### Scenario: Token expired

- **WHEN** access token expires
- **THEN** system automatically requests new token
- **AND** retries the original API call with new token

### Requirement: SF Express Order Creation

The system SHALL create shipping orders via SF Express speed shipping API.

#### Scenario: Create shipping order

- **WHEN** scheduled shipment execution triggers
- **AND** rental has valid `sf_waybill_no`
- **THEN** system constructs order request with:
  - Sender info from environment variables
  - Recipient info from rental (customer_name, phone, destination)
  - Waybill number from rental.sf_waybill_no
  - Service code for speed shipping
- **AND** calls SF Express order creation API
- **AND** receives order confirmation with tracking number

#### Scenario: Map rental data to SF API format

- **WHEN** constructing SF Express order request
- **THEN** system maps fields:
  - `senderName` from config `SF_SENDER_NAME`
  - `senderMobile` from config `SF_SENDER_PHONE`
  - `senderAddress` from config `SF_SENDER_ADDRESS`
  - `recipientName` from rental.customer_name
  - `recipientMobile` from rental.customer_phone
  - `recipientAddress` from rental.destination
  - `waybillNo` from rental.sf_waybill_no

#### Scenario: API returns error

- **WHEN** SF Express API returns error code
- **THEN** system logs error with rental ID, error code, error message
- **AND** throws exception to trigger retry mechanism

### Requirement: SF Express Error Handling

The system SHALL handle SF Express API errors with retry and logging.

#### Scenario: Network error retry

- **WHEN** SF Express API call fails due to network error
- **THEN** system retries up to 3 times
- **AND** uses exponential backoff (1s, 2s, 4s)
- **AND** logs each retry attempt

#### Scenario: API rate limit

- **WHEN** SF Express API returns rate limit error
- **THEN** system waits for retry-after duration
- **AND** retries the request
- **AND** logs rate limit incident

#### Scenario: Permanent failure

- **WHEN** all retry attempts fail
- **THEN** system logs critical error
- **AND** marks rental for manual intervention
- **AND** sends alert to administrators

### Requirement: SF Express Configuration

The system SHALL load SF Express API credentials from environment variables.

#### Scenario: Load credentials

- **WHEN** application starts
- **THEN** system loads from environment:
  - `SF_APP_KEY` - SF Express application key
  - `SF_APP_SECRET` - SF Express application secret
  - `SF_SENDER_NAME` - Sender name
  - `SF_SENDER_PHONE` - Sender phone
  - `SF_SENDER_ADDRESS` - Sender full address
  - `SF_API_MODE` - test or production

#### Scenario: Missing credentials

- **WHEN** required SF Express credentials are missing
- **THEN** system logs warning at startup
- **AND** scheduled shipment task fails with clear error message
- **AND** admin receives notification to configure credentials
