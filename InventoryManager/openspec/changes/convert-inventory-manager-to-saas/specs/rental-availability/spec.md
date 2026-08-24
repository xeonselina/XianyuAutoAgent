## ADDED Requirements

### Requirement: One schedule policy owns hard conflicts and relay warnings
The system MUST use one server-side `ScheduleOverlapPolicy` for booking preview, find-slot compatibility, final create/update, Gantt warnings, relay candidates, and affected-chain recalculation. Inclusive customer-use period overlap SHALL be a hard `USAGE_PERIOD_CONFLICT`; otherwise the policy SHALL calculate planned logistics windows and emit both the Gantt warning and relay candidate only when `overlap_days = predecessor.planned_return_date - successor.planned_ship_out_date` is greater than one day.

#### Scenario: Customer-use periods overlap
- **GIVEN** two active rentals for one main device have overlapping inclusive customer-use dates
- **WHEN** availability or final validation runs
- **THEN** the candidate is unavailable and creation returns HTTP 409 `USAGE_PERIOD_CONFLICT`
- **AND** no soft logistics warning can make the write succeed

#### Scenario: Logistics windows overlap by one day
- **GIVEN** customer-use periods do not overlap and calculated `overlap_days` is one
- **WHEN** Gantt and relay projections are generated
- **THEN** neither surface emits a logistics warning or relay candidate
- **AND** the rental remains submittable

#### Scenario: Logistics windows overlap by two days
- **GIVEN** customer-use periods do not overlap and calculated `overlap_days` is two
- **WHEN** Gantt and relay projections are generated
- **THEN** both surfaces report the same value and adjacent rental identifiers
- **AND** submission remains allowed with `LOGISTICS_OVERLAP_RELAY_WARNING`

### Requirement: Logistics dates preserve the confirmed formula
The system MUST accept `logistics_days` only as an integer from zero through seven, preserve zero, and calculate `planned_ship_out_date = start_date - (logistics_days + 1 day)` and `planned_return_date = end_date + (logistics_days + 1 day)`. Actual ship/return timestamps SHALL NOT overwrite planned fields, which change only after an explicit edit to rental dates or logistics inputs.

#### Scenario: Same-day logistics is selected
- **GIVEN** an operator confirms `logistics_days = 0`
- **WHEN** planned dates are calculated
- **THEN** the system retains zero logistics days and applies exactly the separate one-day operational buffer on each side
- **AND** no truthy fallback silently changes the value to one or three days

### Requirement: Booking bootstrap is one minimal request
The system MUST provide one booking-bootstrap contract containing eligible warehouses and the user's recent selection, device models, configurable accessory types, and other non-inventory form metadata needed by desktop and mobile clients. It SHALL replace separate initial devices/accessories/models requests and MUST NOT depend on a possibly stale Gantt-store device snapshot.

#### Scenario: Mobile new-rental page opens
- **WHEN** the mobile client opens a new-rental form
- **THEN** it makes at most one bootstrap request for initial form metadata
- **AND** it does not load the full Gantt view or a deep rental/device graph

### Requirement: Availability is realtime and warehouse-aware
The system MUST provide one availability request per stable date/model/preferred-warehouse change. It SHALL return candidates sorted by preferred warehouse and existing business order, estimate logistics once per candidate warehouse from the server-resolved structured origin to structured destination, expose hard availability separately from warnings/relay facts, and aggregate logical accessories without returning internal unit IDs.

#### Scenario: Official estimate is unavailable
- **GIVEN** a candidate warehouse has no usable SF estimate or binding
- **WHEN** availability is evaluated
- **THEN** the response names the relevant warehouse and safe failure reason
- **AND** an Admin or Operator must explicitly provide and confirm a zero-to-seven-day value tied to that origin/destination context
- **AND** the server does not silently use Shenzhen or a fixed three-day default

### Requirement: Rental writes revalidate all realtime facts
The system MUST lock the selected device, its current warehouse, accessory requests, existing links, and candidate logical units in stable order during final create/update. It SHALL recompute structured-origin logistics, hard customer-use conflicts, unit linkability, and soft warnings; if the device moved after preview it MUST return HTTP 409 `ORIGIN_WAREHOUSE_CHANGED` with the new safe warehouse/estimate summary rather than silently accepting stale input.

#### Scenario: Device moves between preview and save
- **GIVEN** availability was calculated for warehouse A
- **WHEN** the device moves to warehouse B before final save
- **THEN** final validation makes no rental write and returns `ORIGIN_WAREHOUSE_CHANGED`
- **AND** the client must display and confirm a new warehouse-B estimate before retrying

### Requirement: Gantt range data is one normalized snapshot
The system MUST provide one range-view request that reads a single tenant-database snapshot and returns flat device and rental DTOs, range-wide daily statistics, model facets, approved counts/revisions, and schedule warnings. It SHALL eliminate per-day statistics calls, deep repeated rental nesting, frontend `statsCache`, and synchronous third-party refresh on mount.

#### Scenario: User moves the Gantt window
- **WHEN** the visible window or server-side filter changes once
- **THEN** the page sends at most one core range-view request
- **AND** warnings and daily counts correspond to the same read snapshot
- **AND** no request is issued once per day or per device

### Requirement: One page owner coordinates post-write refresh
The system MUST return a compact authoritative DTO, data revision, and refresh scope from mutations. A single page-level refresh owner SHALL coalesce concurrent signals, cancel stale parameter requests, and issue at most one current-window view refresh; stores, callbacks, and watchers MUST NOT each trigger their own hidden reload.

#### Scenario: A rental edit succeeds
- **WHEN** the write response is accepted by the page
- **THEN** no more than one follow-up current-window view request is made
- **AND** only the latest request sequence may replace visible state

### Requirement: Inventory reads are not persistently cached
The system MUST use realtime tenant-database queries and final write-time validation for device, warehouse, accessory, availability, and statistics facts. Responses SHALL use `Cache-Control: no-store`, and the client MAY only deduplicate in-flight requests; browser persistent caches and cross-request business-result caches MUST NOT decide availability.

#### Scenario: Inventory changes after an earlier response
- **GIVEN** a browser previously viewed an accessory as available
- **WHEN** another transaction allocates the last unit and the first browser submits
- **THEN** final database validation rejects or recalculates the stale choice
- **AND** no local cache can force the old result to commit

### Requirement: Core query and connection budgets prevent tenant fan-out
The system MUST use explicit paginated/projected DTOs, eager/batch loading, a single tenant session per aggregate request, and an approved bounded engine cache/pool budget. Release tests SHALL use at least 100 devices, multiple warehouses and logical units, and 31 days of overlapping rentals to prove that availability and Gantt SQL counts do not grow linearly with candidate devices or displayed days.

#### Scenario: Fixture size grows tenfold
- **GIVEN** the approved query-count fixture is expanded tenfold in devices or date span within the endpoint limit
- **WHEN** availability and Gantt contracts run
- **THEN** HTTP fan-out remains one request per stable user action
- **AND** tenant connection checkout remains one per aggregate request
- **AND** SQL statement count does not grow linearly with the expanded dimension

