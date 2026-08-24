## MODIFIED Requirements

### Requirement: Display batch print waybill button
The system MUST show the `批量打印快递面单` action only inside an authenticated tenant's warehouse-scoped batch-shipping workflow and MUST derive its eligible count from the server-authorized warehouse queue.

#### Scenario: Show count for a selected warehouse
- **GIVEN** a multi-warehouse tenant member selects warehouse A
- **AND** three tenant-owned rentals in warehouse A are eligible for paired-label printing
- **WHEN** the batch-shipping page loads
- **THEN** the button SHALL display count `(3)` and be enabled
- **AND** rentals in warehouse B or another tenant SHALL NOT contribute to the count

#### Scenario: Use the only warehouse automatically
- **GIVEN** the tenant has exactly one active warehouse
- **WHEN** the batch-shipping page loads
- **THEN** the system SHALL select that warehouse without adding a warehouse-selection step
- **AND** the button SHALL use that warehouse's authorized queue

#### Scenario: Disable when no rental is eligible
- **GIVEN** the selected warehouse has no rental that passes status, waybill, attachment, warehouse, and tenant printing gates
- **WHEN** the page calculates the server-returned eligible count
- **THEN** the button SHALL display `(0)` and be disabled

### Requirement: Show warehouse print-context dialog
The system MUST replace direct printer selection with a warehouse-context confirmation dialog that displays the server-resolved printer summary but never lets an operator choose or submit an arbitrary printer.

#### Scenario: Open warehouse printing confirmation
- **GIVEN** a member clicks `批量打印快递面单`
- **WHEN** the confirmation dialog opens
- **THEN** it SHALL show the trusted warehouse, eligible order count, paired-label description, and the masked configured printer summary
- **AND** it SHALL show confirm and cancel actions
- **AND** it SHALL NOT contain a printer dropdown or accept a client-supplied printer ID

#### Scenario: Multiple warehouses require warehouse selection
- **GIVEN** the tenant has more than one active warehouse and none is selected for this page context
- **WHEN** the member starts printing
- **THEN** the UI SHALL require a warehouse selection before showing eligible rentals
- **AND** the server SHALL reject rental IDs outside the selected trusted warehouse queue

#### Scenario: Selected warehouse has no valid printer binding
- **GIVEN** the trusted warehouse lacks an active verified Kuaimai printer binding
- **WHEN** the confirmation dialog loads
- **THEN** confirmation SHALL be disabled with a structured warehouse-specific error
- **AND** an Admin SHALL receive an authorized settings deep link while an Operator SHALL receive contact-Admin guidance
- **AND** neither response SHALL expose printer credentials or another warehouse's configuration

### Requirement: Execute batch printing operation
The system MUST create durable warehouse-scoped print jobs for the selected tenant-owned rentals and MUST route both labels through the exact warehouse, printer, integration revision, and content snapshots committed before provider submission.

#### Scenario: Submit a warehouse-scoped print request
- **GIVEN** the member confirmed five eligible rentals in warehouse A
- **WHEN** the client submits the batch print request
- **THEN** the request SHALL include the selected warehouse, rental IDs, and a stable client operation idempotency key
- **AND** it SHALL NOT include an authoritative printer ID, credential revision, sender, or return address
- **AND** the server SHALL re-authorize and lock the tenant resources before creating jobs

#### Scenario: Create paired labels from one execution context
- **GIVEN** a rental passes the final printing gates
- **WHEN** its durable print job is created
- **THEN** the SF first label and local return-information second label SHALL snapshot the same warehouse and bound printer
- **AND** the second label SHALL snapshot the warehouse return contact, phone, address, order number, due-return date, customer-visible note, and approved tutorial QR codes
- **AND** local return information and the customer-visible note SHALL NOT be sent to SF Express or included on the first label

#### Scenario: Device moved after waybill creation
- **GIVEN** a rental has an existing waybill from warehouse A and its main device now belongs to warehouse B before physical shipment
- **WHEN** either label is requested
- **THEN** printing SHALL be blocked until the old waybill is confirmed cancelled or its unknown cancellation is resolved and a new warehouse-B shipment is created
- **AND** the system SHALL never pair a warehouse-A first label with a warehouse-B second label

#### Scenario: Durable creation completes before provider submission
- **GIVEN** all authorization and business gates pass
- **WHEN** the server accepts the print command
- **THEN** it SHALL commit the immutable job snapshots and outbox work before any Kuaimai network call
- **AND** the response SHALL identify the durable operation without holding a tenant database transaction during provider I/O

### Requirement: Display printing results
The system MUST display per-label and aggregate outcomes from durable print-job state, distinguishing success, definitive failure, pending work, and unknown submission.

#### Scenario: All paired labels complete
- **GIVEN** five orders each have a completed first-label attempt and completed second-label attempt
- **WHEN** the UI refreshes operation status
- **THEN** it SHALL show five successful orders, zero failed orders, and completion at 100 percent

#### Scenario: One label in a pair fails
- **GIVEN** an order's first label completed and its second label definitively failed
- **WHEN** results are displayed
- **THEN** the order SHALL be shown as partially failed
- **AND** the UI SHALL identify the failed label kind and a safe actionable error without exposing credentials, full provider payloads, customer phone numbers, or addresses

#### Scenario: Submission outcome is unknown
- **GIVEN** a label attempt may have reached Kuaimai but no definitive result is available
- **WHEN** results are displayed
- **THEN** the UI SHALL show `待核对` or equivalent `needs_review` state separately from failure
- **AND** it SHALL NOT offer that item as an automatic retry

### Requirement: Handle printing errors gracefully
The system MUST present stable structured printing errors and MUST preserve durable operation state when browser, application, or provider communication fails.

#### Scenario: Browser loses the submission response
- **GIVEN** the durable batch operation was committed but the browser did not receive the response
- **WHEN** the client retries with the same tenant, warehouse, payload digest, and idempotency key
- **THEN** the server SHALL return the original operation rather than create duplicate print jobs
- **AND** the UI SHALL resume status display for that operation

#### Scenario: Server rejects stale or unauthorized input
- **GIVEN** a rental changed warehouse, became ineligible, belongs to another tenant, or no longer matches the submitted snapshot
- **WHEN** the print command is finalized
- **THEN** the server SHALL reject that item or the atomic command according to the documented batch policy before provider submission
- **AND** the response SHALL use a safe structured error without revealing another tenant's object existence

#### Scenario: Provider communication fails
- **GIVEN** Kuaimai returns a definitive failure or communication becomes uncertain
- **WHEN** the durable attempt is reconciled
- **THEN** the UI SHALL remain usable and display the persisted definitive-failure or `needs_review` state
- **AND** detailed secrets, full payloads, and PII SHALL NOT be logged to the browser console or server logs

### Requirement: Provide retry mechanism
The system MUST allow retry only for attempts proven not submitted or definitively failed and MUST require review plus an explicit new reprint for an unknown submission.

#### Scenario: Retry a definitive failed label
- **GIVEN** a label attempt is definitively failed and the original warehouse, printer binding, and credential revision remain usable
- **WHEN** an authorized member selects `重试失败项`
- **THEN** the system SHALL retry only eligible failed label attempts using their immutable execution snapshots and stable original idempotency identity
- **AND** successful labels in the pair SHALL NOT be printed again

#### Scenario: Snapshot can no longer be used
- **GIVEN** the original printer or credential revision is unavailable or fails authenticated resolution
- **WHEN** retry is requested
- **THEN** the system SHALL fail closed or enter `needs_review`
- **AND** it SHALL NOT switch to a current printer, another warehouse, or new credentials silently

#### Scenario: Explicit reprint after unknown outcome
- **GIVEN** an authorized user has reconciled an unknown attempt and decides a physical reprint is necessary
- **WHEN** the user confirms the reprint
- **THEN** the system SHALL create a new auditable print job and idempotency identity linked to the original attempt
- **AND** it SHALL clearly mark the action as a reprint rather than mutate or replay the uncertain attempt

### Requirement: Close dialog after successful completion
The system MUST close the dialog automatically only after every label in the durable operation reaches a successful terminal state and MUST keep non-success outcomes available for review.

#### Scenario: Auto-close after durable success
- **GIVEN** every paired-label attempt is durably recorded as completed
- **WHEN** the success result has been displayed for the configured interval
- **THEN** the dialog SHALL close and the warehouse queue SHALL refresh at most once

#### Scenario: Keep dialog open for failure or review
- **GIVEN** any attempt is failed, pending, partially completed, or `needs_review`
- **WHEN** operation status is displayed
- **THEN** the dialog SHALL remain open or provide an equivalent persistent operation view
- **AND** the user SHALL be able to inspect safe details and allowed next actions

### Requirement: Disable button during printing
The system MUST combine client loading controls with server-side idempotency and active-operation exclusion so concurrent clicks, tabs, or application instances cannot create duplicate print attempts.

#### Scenario: Prevent a duplicate click in one browser
- **GIVEN** the browser is submitting a print command
- **WHEN** the user clicks the action again
- **THEN** the button SHALL remain disabled and the browser SHALL NOT send a second new command

#### Scenario: Deduplicate across tabs or instances
- **GIVEN** two clients concurrently submit the same tenant, warehouse, rental set, payload digest, and idempotency key
- **WHEN** the server processes both requests
- **THEN** at most one durable print operation SHALL be created
- **AND** both clients SHALL observe the same operation identifier and state

#### Scenario: Idempotency key is reused with different input
- **GIVEN** an existing idempotency key is submitted with a different warehouse, rental set, or payload digest
- **WHEN** the server validates the request
- **THEN** it SHALL reject the request without creating or submitting any new print job

## REMOVED Requirements

### Requirement: Persist printer selection
**Reason**: SaaS Core binds at most one active Kuaimai printer to each warehouse and operators select only the warehouse. A browser-local printer preference could silently route another tenant's or warehouse's labels to the wrong device.

**Migration**: Remove and ignore the legacy printer-selection `localStorage` key. Migrate the intended physical printer through the authenticated Admin warehouse-binding flow; remember only the user's last warehouse per workflow on the server-side account preference, never an authoritative printer ID in browser storage.

#### Scenario: Legacy browser printer preference is ignored
- **GIVEN** a browser still contains a legacy saved printer ID
- **WHEN** the SaaS batch-print workflow opens or submits a command
- **THEN** the system SHALL ignore and remove that preference
- **AND** it SHALL resolve the printer only from the trusted tenant warehouse binding

## RENAMED Requirements

- FROM: `### Requirement: Show printer selection dialog`
- TO: `### Requirement: Show warehouse print-context dialog`
