## MODIFIED Requirements

### Requirement: Retrieve waybill PDF from SF Express
The system MUST obtain a waybill PDF only within an authorized tenant operation and MUST resolve the SF execution context from the shipment ledger rather than from client-supplied or current global configuration.

#### Scenario: Retrieve a waybill from its immutable shipment context
- **GIVEN** an active tenant member is authorized to print a rental waybill
- **AND** the shipment ledger contains the original tenant, warehouse, provider account, integration, binding revision, exact integration secret revision UUID, exact provider-account secret revision UUID, sender snapshot, and tracking number
- **WHEN** the system calls SF Express `COM_RECE_CLOUD_PRINT_WAYBILLS`
- **THEN** it SHALL authenticate with those exact historical revisions and return the waybill PDF bytes
- **AND** it SHALL NOT re-resolve the current warehouse binding, current credential pointer, another warehouse, or process environment credentials

#### Scenario: Reject a cross-tenant or incomplete waybill lookup
- **GIVEN** the authenticated tenant does not own the rental or shipment
- **OR** the shipment lacks a tracking number or any required immutable execution reference
- **WHEN** waybill PDF retrieval is requested
- **THEN** the system SHALL fail closed without calling SF Express
- **AND** the response SHALL NOT reveal whether another tenant owns the object or expose credentials, sender data, or provider response bodies

#### Scenario: Reject PDF retrieval for legacy-unattributed history
- **GIVEN** the requested record is a D68 `legacy_unattributed` snapshot rather than a Core shipment with exact credential revisions
- **WHEN** waybill PDF retrieval is requested
- **THEN** the system SHALL return a stable read-only-history result without calling SF Express
- **AND** it SHALL NOT attach a current credential, create a provider operation, or expose a retry/reprint action

#### Scenario: Historical credential is no longer usable
- **GIVEN** the shipment references an immutable credential revision that is missing, cannot be authenticated, or has been revoked by SF Express
- **WHEN** the waybill PDF is requested
- **THEN** the system SHALL return a stable credential-invalid or `needs_review` result
- **AND** it SHALL NOT fall back to a current, default, global, or newly bound credential

### Requirement: Construct SF API request with rental details
The system MUST construct each SF request from trusted tenant data and the shipment execution snapshot, including only fields supported by the selected SF API.

#### Scenario: Construct the original shipment request
- **GIVEN** an authorized rental and a trusted shipment execution context
- **WHEN** the system constructs an SF request for that shipment
- **THEN** the request SHALL use a stable PII-free provider order ID derived from a non-sensitive tenant identifier and immutable shipment UUID
- **AND** required receiver data SHALL come from the tenant-owned rental
- **AND** sender contact and address SHALL come from the shipment's warehouse snapshot
- **AND** the scheduled dispatch time and single-package cargo details SHALL come from the immutable shipment snapshot produced from the authorized request and locked main device
- **AND** an idempotent retry SHALL reuse those exact scheduled-time and cargo facts rather than reread mutable rental or device display data
- **AND** the local return address and customer-visible second-label note SHALL NOT be added to the SF first-label payload unless that SF API explicitly requires the field

#### Scenario: Client attempts to override routing data
- **GIVEN** a client supplies a warehouse ID, monthly account, provider account UUID, sender, origin, credential revision, or return-note field that differs from the trusted context
- **WHEN** the SF request is constructed
- **THEN** the system SHALL ignore or reject the untrusted override
- **AND** it SHALL NOT route the request through another tenant, warehouse, account, or credential

### Requirement: Handle API authentication
The system MUST use SF `msgDigest` authentication with an explicitly resolved immutable integration and provider-account secret revision, and MUST never read tenant SF business credentials directly from process environment variables.

#### Scenario: Authenticate a new SF operation
- **GIVEN** the active tenant and device warehouse have an active verified binding whose claim, account, connection, and current secret-revision pointers are consistent
- **WHEN** a new SF operation is durably created
- **THEN** the system SHALL snapshot the exact integration and provider-account secret revision UUIDs before the provider call
- **AND** the adapter SHALL generate `msgDigest`, timestamp, and request ID from credentials decrypted only for that short-lived call

#### Scenario: Authenticate a historical SF operation
- **GIVEN** an existing shipment was created with credential revisions v1 and the tenant later activated v2
- **WHEN** an authorized cancellation, reconciliation, tracking query, idempotent retry, or first-label retrieval is performed for the existing shipment
- **THEN** the system SHALL authenticate with the v1 revision UUIDs recorded by that shipment
- **AND** it SHALL NOT follow v2 current pointers or a new warehouse claim owner

#### Scenario: Credential context is tampered with
- **GIVEN** a ciphertext, tenant UUID, provider, integration UUID, provider account UUID, revision, or authenticated metadata is substituted
- **WHEN** the credential is resolved
- **THEN** authenticated decryption SHALL fail closed before any SF request
- **AND** no credential material or full provider request SHALL be written to logs, API responses, or audit payloads

### Requirement: Support API retry on transient failures
The system MUST distinguish a request that is known not to have produced a provider side effect from a request whose submission result is unknown, and MUST preserve the original execution snapshot and stable idempotency identity on every permitted retry.

#### Scenario: Retry a read-only waybill retrieval
- **GIVEN** a waybill PDF retrieval fails with a transient network error before a response is received
- **WHEN** the retry policy runs
- **THEN** the system SHALL retry at most two times with bounded backoff
- **AND** every attempt SHALL use the same tenant, shipment, warehouse, account, binding, credential revisions, and request identity

#### Scenario: Do not retry an SF business error
- **GIVEN** SF Express returns a definitive business error such as `运单号不存在`
- **WHEN** the response is classified
- **THEN** the system SHALL NOT automatically retry
- **AND** it SHALL persist a safe result code without logging the full request, response, credentials, phone numbers, or addresses

#### Scenario: Submission outcome is unknown
- **GIVEN** a state-changing SF request may have reached SF Express but the response is lost or times out
- **WHEN** the worker cannot prove that no side effect occurred
- **THEN** the execution SHALL enter an unknown or `needs_review` state
- **AND** the system SHALL query or reconcile by the original PII-free provider order ID and idempotency key before any further submission
- **AND** it SHALL NOT create a second shipment, switch credentials, or blindly replay the provider call
