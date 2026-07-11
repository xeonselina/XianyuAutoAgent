## ADDED Requirements

### Requirement: Eligible Schedule Reordering

The system SHALL reassign only main rentals whose status is `not_shipped`, whose ship-out date is today or later in `Asia/Shanghai`, and whose ship-out time and model ID are present. The system SHALL assign each eligible rental exactly once to a non-accessory device with the same `model_id`, `status = online`, and `lifecycle_status = active`.

#### Scenario: Reorder eligible future rentals

- **WHEN** an operator previews reordering for future unshipped main rentals
- **THEN** each eligible rental is assigned exactly once to an online, active, same-model main device
- **AND** no rental date or status changes

#### Scenario: Exclude ineligible rentals

- **WHEN** a rental is scheduled for shipping, shipped, in progress, cancelled, a child rental, before today, or missing logistics/model data
- **THEN** the system does not move that rental
- **AND** it reports skipped records where operator attention is useful

### Requirement: Schedule Compression

The system SHALL optimize each model independently using OR-Tools CP-SAT, first minimizing the number of devices carrying movable future schedules, then total idle days between consecutive logical schedule blocks, then the number of changed device assignments.

#### Scenario: Compress schedules within a model

- **WHEN** multiple legal assignments exist for rentals of one model
- **THEN** the system prefers fewer used target devices
- **AND** prefers smaller schedule gaps and fewer device changes in that order

#### Scenario: Model is infeasible

- **WHEN** no legal assignment exists for one model
- **THEN** that model retains its original assignments
- **AND** the preview identifies the model and reason

### Requirement: Allowed Turnaround

The system SHALL allow normal consecutive rentals on one device when the next ship-out calendar date equals or follows the previous ship-in calendar date. It SHALL prohibit a next ship-out date earlier than the previous ship-in date unless the rentals belong to a confirmed relay chain.

#### Scenario: Same-day turnaround

- **WHEN** one rental is received in the morning and the next is sent later on the same calendar day
- **THEN** the solver may place both rentals on the same device

#### Scenario: Unconfirmed multi-day overlap

- **WHEN** consecutive rentals overlap beyond the same-day allowance and have no relay binding decision
- **THEN** the system blocks final preview until the operator chooses to bind or separate them

### Requirement: Persistent Relay Bindings

The system SHALL let operators permanently bind chronological, same-model main rentals as a non-branching relay chain. All members of a relay chain SHALL remain on one device, and a chain containing a fixed rental SHALL remain on that fixed rental's device.

#### Scenario: Confirm a new relay

- **WHEN** the operator selects “保持接力并永久绑定” for an unconfirmed overlap and executes the preview
- **THEN** the system persists the predecessor/successor binding in the same transaction as reordering
- **AND** keeps both rentals on the same device

#### Scenario: Preserve an existing relay chain

- **WHEN** A → B → C is already bound
- **THEN** subsequent reorder previews treat the chain as indivisible and default to preserving it

#### Scenario: Remove a relay binding

- **WHEN** the operator chooses to remove an existing binding
- **THEN** the preview must assign the resulting rentals without unauthorized overlap
- **AND** execution removes the binding atomically with device changes

### Requirement: Parent-Child Rental Integrity

The system SHALL never optimize a child rental. Reordering a main rental SHALL preserve every child rental's ID, `device_id`, `parent_rental_id`, dates, logistics times, status, and membership in the parent rental's child set.

#### Scenario: Main rental with a phone stand

- **WHEN** a phone main rental with a phone-stand child rental moves to another same-model phone
- **THEN** the phone-stand child rental remains on its original accessory device
- **AND** remains linked to the same main rental

#### Scenario: Child rental changes after preview

- **WHEN** any child rental is added, removed or changed after preview
- **THEN** execute rejects the stale preview and performs no writes

### Requirement: Preview Before Execution

The system SHALL use a two-step workflow: relay confirmation followed by a no-write result preview. The preview SHALL show customer name, phone, address, schedule, original device, target device, model summaries, solver status, skipped records and errors. The second step SHALL execute directly without a third confirmation page.

#### Scenario: Generate preview

- **WHEN** all overlap decisions are complete
- **THEN** the system returns a signed ten-minute preview token and detailed proposed changes
- **AND** performs no database writes

#### Scenario: Return to relay choices

- **WHEN** the operator selects “返回修改接力”
- **THEN** the interface returns to step one without persisting choices

### Requirement: Atomic and Stale-Safe Execution

The system SHALL lock related rentals, children, devices and bindings; verify the signed snapshot; validate the preview assignment with pinned solver variables; and update bindings, eligible main rental device IDs, and audit logs in one transaction. Any failure SHALL roll back the complete operation.

#### Scenario: Execute unchanged preview

- **WHEN** the token is valid and all snapshot and feasibility checks pass
- **THEN** execution applies exactly the device mapping shown in preview
- **AND** writes audit details for every changed main rental

#### Scenario: Data changes after preview

- **WHEN** a related rental, child, device state or binding changes before execute
- **THEN** the system rejects execution and requests a new preview
- **AND** no partial update is committed

#### Scenario: Failure during execution

- **WHEN** a database or invariant failure occurs after updates begin
- **THEN** all device, relay and audit changes from the operation are rolled back
- **AND** the pre-execution rental ID sets and values remain intact

### Requirement: Active Device Slot Lookup

The system SHALL return only devices whose operational status is online and lifecycle status is active when finding a slot for a new rental, for both main-device and accessory lookup paths.

#### Scenario: Lifecycle-inactive online device

- **WHEN** an online device is sold, damaged, decommissioned, or retired
- **THEN** new-rental slot lookup does not return that device

#### Scenario: Active offline device

- **WHEN** a lifecycle-active device is offline
- **THEN** new-rental slot lookup does not return that device

### Requirement: Production Database Test Isolation

Automated tests SHALL NOT load the production `.env`, connect to a `192.*` database host, or use a database name without `test`. MySQL transaction tests SHALL use an isolated container and synthetic data by default.

#### Scenario: Unsafe test database URL

- **WHEN** a test starts with a `192.*` host, a non-test database name, or without `TESTING=true`
- **THEN** the test bootstrap terminates before opening a database connection

#### Scenario: Production-like data is required

- **WHEN** synthetic fixtures cannot reproduce an issue and separate authorization is granted
- **THEN** a read-only single-transaction dump is imported into an isolated database and anonymized before tests run

### Requirement: Containerized OR-Tools Deployment

The system SHALL install a pinned OR-Tools Python package inside the application image and SHALL support the existing Linux amd64 and arm64 Docker targets without requiring OR-Tools installation on the NAS host.

#### Scenario: Multi-architecture image build

- **WHEN** application images are built for amd64 and arm64
- **THEN** both images can import `ortools.sat.python.cp_model`
