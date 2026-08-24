## MODIFIED Requirements

### Requirement: Authenticate with Kuaimai API
The system MUST generate valid Kuaimai MD5 signatures from the exact immutable tenant integration secret revision recorded by the configuration validation or print job, and MUST NOT read tenant Kuaimai credentials directly from process environment variables.

#### Scenario: Sign a request for an active tenant integration
- **GIVEN** an active tenant has a verified Kuaimai integration revision containing `appId` and `appSecret`
- **WHEN** the adapter signs a Kuaimai request
- **THEN** it SHALL sort provider parameters in ASCII key order, construct the provider-defined signing input, and return the required lowercase MD5 signature
- **AND** the request SHALL include the revision's `appId`, timestamp, signature, and required content type

#### Scenario: Use the print job's historical credential revision
- **GIVEN** a print job snapshots Kuaimai credential revision v1 and the tenant later activates v2
- **WHEN** the system queries or safely resumes that job
- **THEN** it SHALL use v1 recorded on the job
- **AND** it SHALL NOT use v2, another tenant's integration, or a global default

#### Scenario: Credential authentication fails
- **GIVEN** the secret revision is missing, belongs to another tenant, or fails authenticated decryption
- **WHEN** a Kuaimai operation is attempted
- **THEN** the system SHALL fail closed before the provider call
- **AND** no `appSecret`, ciphertext, full request, or full response SHALL appear in logs or API responses

### Requirement: Send print job to Kuaimai printer
The system MUST submit each image through the printer bound to the print job's trusted warehouse and MUST durably snapshot tenant, warehouse, printer serial number, integration secret revision, label kind, and stable idempotency identity before calling Kuaimai.

#### Scenario: Submit a warehouse-routed paired-label job
- **GIVEN** all selected rentals belong to the authenticated tenant and trusted warehouse queue
- **AND** that warehouse has one active verified Kuaimai printer binding
- **WHEN** the system submits the SF first label and local return-information second label
- **THEN** both labels SHALL use the same snapshotted warehouse, printer serial number, and integration revision
- **AND** the system SHALL send the encoded images in the required order with the configured copy count
- **AND** it SHALL persist each returned provider task ID separately

#### Scenario: Warehouse printer is unavailable
- **GIVEN** the trusted warehouse has no active binding, its printer is offline, or its binding validation failed
- **WHEN** printing is requested
- **THEN** the system SHALL return a structured actionable printing error without submitting any label that cannot be safely paired
- **AND** it SHALL NOT fall back to another warehouse's printer, a process-wide printer, or a client-supplied printer ID

#### Scenario: Print submission result is unknown
- **GIVEN** the Kuaimai request may have been accepted but the response or provider task ID is lost
- **WHEN** the worker cannot prove that the label was not submitted
- **THEN** the item SHALL enter `needs_review` with its immutable execution snapshot
- **AND** the system SHALL NOT automatically submit the label again
- **AND** an authorized explicit reprint after review SHALL create a new print job and idempotency identity rather than mutate the uncertain attempt

### Requirement: List available printers
The system MUST list Kuaimai printers only for an authorized active-tenant Admin configuration flow and MUST keep all results scoped to the selected tenant integration revision.

#### Scenario: Admin validates a warehouse printer binding
- **GIVEN** an active tenant Admin is configuring a warehouse
- **WHEN** the Admin requests available printers for the tenant's verified Kuaimai integration
- **THEN** the system SHALL return only safe printer identifiers, names, and provider status needed for binding
- **AND** binding validation SHALL prove that the selected printer belongs to that integration before the warehouse pointer is changed

#### Scenario: Runtime operator opens the print workflow
- **GIVEN** an Operator opens batch printing for a warehouse
- **WHEN** the page resolves the printing context
- **THEN** the system SHALL return the warehouse's configured printer summary without offering an arbitrary printer list or printer selector
- **AND** it SHALL NOT expose credentials or printers belonging to another tenant

#### Scenario: Cached printer data crosses a security boundary
- **GIVEN** printer metadata was previously fetched for another tenant or an older integration revision
- **WHEN** a printer list or binding is validated
- **THEN** the system SHALL NOT reuse that data as authority
- **AND** any short-lived cache SHALL be keyed by tenant and exact integration revision and SHALL never authorize a print or binding without a current server-side check

### Requirement: Track print job status
The system MUST track Kuaimai status by the provider task ID and immutable print-attempt snapshot, while keeping success, definitive failure, and unknown submission as distinct states.

#### Scenario: Track a completed print attempt
- **GIVEN** a print attempt has a recorded provider task ID
- **WHEN** Kuaimai reports completion
- **THEN** the system SHALL persist `completed` with the completion timestamp for that exact label attempt
- **AND** completion of one label SHALL NOT imply that its paired label completed

#### Scenario: Track a definitive failed attempt
- **GIVEN** Kuaimai reports a terminal failure for a recorded provider task ID
- **WHEN** status is reconciled
- **THEN** the system SHALL persist `failed` with a safe failure code
- **AND** it SHALL retain the original warehouse, printer, credential revision, and label-kind snapshot for an allowed retry

#### Scenario: Status cannot prove submission outcome
- **GIVEN** no provider task ID was returned and reconciliation cannot prove whether submission occurred
- **WHEN** status is evaluated
- **THEN** the system SHALL retain `needs_review`
- **AND** it SHALL NOT convert the attempt to `failed` merely to enable an automatic duplicate print

### Requirement: Handle API rate limiting
The system MUST respect Kuaimai rate limits with bounded backoff and MUST retry only when the persisted attempt proves the provider did not accept the submission or when a read-only status query is safe to repeat.

#### Scenario: Rate limit before print acceptance
- **GIVEN** Kuaimai definitively rejects a submission with a rate-limit response and no provider task is created
- **WHEN** the retry policy runs
- **THEN** the system SHALL use bounded backoff and the original idempotency identity and immutable snapshot
- **AND** it SHALL stop after the configured attempt limit

#### Scenario: Rate limit during status query
- **GIVEN** a read-only status query is rate limited
- **WHEN** the worker retries
- **THEN** it SHALL preserve the provider task ID and use bounded backoff
- **AND** it SHALL NOT resubmit the image as part of status recovery

### Requirement: Validate configuration on initialization
The system MUST resolve Kuaimai configuration per authorized tenant and warehouse, validate new immutable secret revisions asynchronously without holding a database transaction, and fail closed when no current verified revision or printer binding exists.

#### Scenario: Tenant integration is not configured
- **GIVEN** an active tenant has no verified current Kuaimai integration revision
- **WHEN** printing or printer binding is requested
- **THEN** the system SHALL return a stable configuration-required result without calling Kuaimai
- **AND** it SHALL NOT inspect `KUAIMAI_APP_ID`, `KUAIMAI_APP_SECRET`, or a global service singleton as a fallback

#### Scenario: New credential revision is validated
- **GIVEN** an authorized Admin has completed the action-bound verification required to update Kuaimai credentials
- **WHEN** the new pending revision is submitted for validation
- **THEN** the worker SHALL validate that exact revision outside the control transaction
- **AND** only a successful current-version comparison-and-swap SHALL make it current
- **AND** failure or an unknown response SHALL leave the prior current revision unchanged

#### Scenario: Warehouse binding is missing
- **GIVEN** the tenant integration is valid but the trusted print-job warehouse has no active verified printer binding
- **WHEN** printing is requested
- **THEN** the system SHALL block only the printing action with a warehouse-specific actionable error
- **AND** it SHALL NOT block unrelated rental editing or an independently completed SF shipment
