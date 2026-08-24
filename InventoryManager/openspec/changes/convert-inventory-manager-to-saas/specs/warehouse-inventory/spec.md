## ADDED Requirements

### Requirement: Every tenant has a ready default warehouse before business use
The system MUST keep at least one active default warehouse for every tenant. Provisioning SHALL create one pending default warehouse whose phone may be prefilled from registration but is not considered confirmed; the first Admin MUST confirm its name, contact, phone, province, city, district, and detailed address before any inventory, rental, shipping, printing, or inspection API is allowed.

#### Scenario: Direct API call bypasses the setup screen
- **GIVEN** a newly registered tenant has a default warehouse with `setup_state=pending`
- **WHEN** its Admin directly calls a business API
- **THEN** the backend rejects the request with `tenant_setup_required`
- **AND** only account security, subscription renewal, warehouse setup, and logout remain available

### Requirement: Serialized devices have one current warehouse
The system MUST assign every serialized main device to exactly one active warehouse; a new device defaults to the tenant's default warehouse unless another valid warehouse is chosen. Warehouse UUIDs SHALL be interpreted only after trusted tenant routing and MUST NOT be accepted as cross-tenant authorization.

#### Scenario: Device is created with another tenant's warehouse UUID
- **GIVEN** an authenticated tenant user submits a warehouse UUID owned by another tenant
- **WHEN** the device create transaction resolves the target
- **THEN** no warehouse is found in the trusted tenant database
- **AND** no device or cross-tenant reference is created

### Requirement: Device warehouse changes are explicit and atomic
The system MUST let Admins and Operators move a device only through a dedicated preview-and-confirm action. The confirmation transaction SHALL update current location, append movement history, and recompute future unshipped accessory-unit links in a fixed lock order; it MUST NOT silently change rental logistics days, planned dates, estimate snapshots, Gantt warnings, or relay candidates.

#### Scenario: Move affects future rentals
- **GIVEN** a device has unshipped future rentals and accessory links in its current warehouse
- **WHEN** an authorized user requests a move preview
- **THEN** the preview lists order number, customer-use dates, logistics days, planned ship/return dates, and affected accessories
- **AND** it states that those rental fields will not be recalculated
- **WHEN** the user confirms against the current revision
- **THEN** location, movement history, link reassignment, and resulting shortage facts commit together or all roll back

### Requirement: Warehouse selection does not split a rental
The system MUST keep each rental on one main device, one dispatch warehouse at any instant, one package, and one formal SF waybill. A preferred warehouse SHALL only sort device availability; after a main device is selected, its current warehouse becomes the authoritative inventory and logistics context, and the system MUST NOT borrow accessories across warehouses or create a second formal shipment.

#### Scenario: User chooses a device outside the preferred warehouse
- **GIVEN** availability lists devices from the preferred and other warehouses
- **WHEN** the user selects an available device from another warehouse
- **THEN** accessories, logistics estimate, SF prerequisites, and later final validation use that device's warehouse
- **AND** no item from the preferred warehouse is silently attached to the package

### Requirement: Accessory types use confirmed tracking modes
The system MUST represent configurable accessories as either `device_bound` types attached to a main device or `logical_unit` types whose warehouse quantity is backed by one internal unit per capacity. Users SHALL choose only accessory types and quantities; internal logical-unit UUIDs MUST NOT appear in UI options, public APIs, exports, labels, logs, QR codes, or printed sheets.

#### Scenario: User requests a logical-unit accessory
- **GIVEN** a main device enables the tripod accessory type
- **WHEN** the booking form displays availability
- **THEN** it shows realtime total, reserved, and available counts for the device's warehouse and target window
- **AND** it does not expose or allow selection of a specific logical-unit identifier

### Requirement: Logical-unit allocation is a locked realtime fact
The system MUST derive logical-unit quantity and availability from unit, holder, request, and link records without a second mutable allocation-total table. A normal rental transaction SHALL lock candidates in stable order and link one active same-warehouse unit whose window does not conflict; two concurrent requests for the last eligible unit can have at most one normal allocation winner.

#### Scenario: Two rentals request the last tripod
- **GIVEN** one eligible tripod unit remains for overlapping windows in a warehouse
- **WHEN** two create transactions concurrently request it
- **THEN** one transaction may create the link
- **AND** the other rolls back with `ACCESSORY_UNIT_UNAVAILABLE`
- **AND** no duplicate link, negative quantity, or persistent conflict-status row is created

### Requirement: Relay links model movement without synthetic statuses
The system MUST represent a logical accessory's planned or actual traversal with neutral rental-unit links and immutable events, not `carryover_only`, `relay_dependent`, `supplemental_dispatch`, or other special allocation statuses. A relay candidate SHALL NOT move or reserve the predecessor's unit; when an edge becomes `agreed`, the service SHALL recompute the downstream agreed chain and link the same unit, including through an intermediate rental that did not request that type.

#### Scenario: Relay agreement order is reversed
- **GIVEN** B-to-C is agreed before A-to-B and A currently holds the required unit
- **WHEN** A-to-B becomes agreed
- **THEN** the service recomputes from A forward and establishes a consistent A-to-B-to-C link chain
- **AND** B without a request dynamically shows that it must carry the unit onward
- **AND** no fake accessory demand or status is stored for B

#### Scenario: Actual handoff is out of order
- **GIVEN** B-to-C is agreed but the unit holder is still A
- **WHEN** B-to-C is marked shipped
- **THEN** the transaction rejects the handoff because B is not the current holder
- **AND** the unit remains unavailable to unrelated rentals

### Requirement: Unmet accessory facts gate normal fulfillment
The system MUST block ordinary SF ordering, batch shipping, and two-sheet printing whenever a rental has an accessory request without a satisfied unit link. A confirmed relay may retain a non-blocking pending-confirmation warning, and the confirmed low-frequency relay supplemental-dispatch exception may keep a shortage request and internal note without inventing a second automated waybill or tracking workflow.

#### Scenario: Device moves to a warehouse with no matching unit
- **GIVEN** an unshipped rental requests a logical accessory and its device is moved to another warehouse with none available
- **WHEN** link reassignment completes
- **THEN** the old-warehouse link is removed and the request remains visibly unsatisfied
- **AND** device location still reflects reality
- **AND** normal ordering, batch shipping, and printing are blocked until the fact is resolved

### Requirement: Inspection updates physical location and custody together
The system MUST require an inspection warehouse when multiple warehouses exist and SHALL commit inspection creation, device location, movement history, and received logical-unit custody/warehouse changes in one transaction. Received units move to the inspection warehouse; missing or unmatched accessories MUST NOT be made available or moved by assumption.

#### Scenario: Accessory is not received during inspection
- **GIVEN** the rental has a linked unit still held by that rental
- **WHEN** inspection records that the accessory was not received
- **THEN** the holder is not cleared and its warehouse is not changed
- **AND** the unit enters the appropriate lost or review fact and cannot be allocated as available

### Requirement: Warehouse history is retained
The system MUST prevent direct deletion or deactivation of the current default warehouse and SHALL require another active warehouse to become default first. Warehouses referenced by devices, rentals, shipments, print jobs, inspections, or audit history SHALL be deactivated rather than physically deleted so immutable contexts remain resolvable.

#### Scenario: Admin attempts to delete a referenced warehouse
- **GIVEN** a non-default warehouse appears in historical shipment snapshots
- **WHEN** an Admin removes it from current operations
- **THEN** it becomes inactive for new selection
- **AND** historical shipment and print contexts remain readable and unchanged

