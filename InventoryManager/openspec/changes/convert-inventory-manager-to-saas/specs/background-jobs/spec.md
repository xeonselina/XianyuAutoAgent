## ADDED Requirements

### Requirement: Run scheduling and durable work outside Web processes

SaaS Core MUST use control-database `background_jobs` with one independent background process that owns APScheduler triggers and job execution; Web processes SHALL NOT start schedulers or rely on process memory or local file locks as the durable source of scheduled work.

#### Scenario: A Web instance starts or rolls
- **WHEN** the Flask application factory initializes
- **THEN** it SHALL serve requests without registering or starting APScheduler jobs

#### Scenario: The background process restarts
- **WHEN** in-memory scheduler or worker state is lost
- **THEN** durable pending, leased, terminal, and review state SHALL remain recoverable from MySQL without duplicating completed executions

### Requirement: Create tenant-scoped versioned jobs

Every normal business job MUST contain a server-issued tenant UUID, tenant access version, job type, resource or period identifier, stable idempotency key, requester provenance, and `not_after` for time-sensitive work; clients SHALL NOT supply or override trusted tenant or access-version fields.

#### Scenario: A platform trigger fans work out to tenants
- **WHEN** a scheduled cycle becomes due
- **THEN** the scheduler SHALL create independent per-tenant jobs in short transactions rather than scan or process every tenant inside one long transaction
- **AND** it SHALL skip tenants whose current recovery coverage or effective gate does not allow normal business jobs

#### Scenario: A duplicate trigger is evaluated
- **WHEN** a job with the same tenant, job type, resource or period, and idempotency key already has an effective execution
- **THEN** the scheduler SHALL reuse or reject the duplicate instead of creating a second effective execution

### Requirement: Claim work with MySQL leases and fencing

The worker MUST claim normal jobs using MySQL 8 row locking and persisted leases with monotonically effective fencing identity, allow expired leases to be recovered, and guarantee at most one effective execution per idempotency key.

#### Scenario: A worker dies while holding a lease
- **WHEN** the persisted lease expires without a terminal result
- **THEN** a later worker MAY reclaim the job using a new fencing identity and SHALL reject writes or side effects carrying the stale lease token

#### Scenario: Two workers race for one job
- **WHEN** both attempt to claim the same effective idempotency key
- **THEN** MySQL locking and uniqueness constraints SHALL allow only one current execution lease

### Requirement: Revalidate tenant authority at every execution boundary

The worker MUST revalidate the external deployment marker, current recovery run and tenant hold, route and access version, active subscription, suspension state, and deletion state after claim, before entering tenant context, before the durable provider-submission boundary, and before every external side effect; stale payloads and leases SHALL never override current tenant authority.

#### Scenario: A queued job belongs to a now-expired tenant
- **WHEN** the worker attempts to claim or execute the job after subscription expiry
- **THEN** it SHALL deny new business execution without opening the tenant database or calling a provider

#### Scenario: Suspension, deletion, or recovery fencing wins a race
- **WHEN** the authoritative tenant transaction advances access or hold state before the job crosses its durable provider boundary
- **THEN** the job SHALL become blocked or terminal under that gate and SHALL NOT renew a stale lease to continue

#### Scenario: An operation had already crossed the boundary
- **WHEN** the tenant is fenced after `provider_submitting` was durably committed
- **THEN** the worker SHALL limit follow-up to safe query or reconciliation using the immutable execution ledger and SHALL NOT automatically resubmit, print, or resolve against a current binding

### Requirement: Persist a linearizable provider-submission boundary

Before any third-party write call, the system MUST commit a short control-plane transaction that locks `tenant → current recovery run → tenant hold → deletion → suspension → job/execution`, rechecks the current active gate and access version, and atomically advances the operation to `provider_submitting`; an in-memory flag, log timestamp, or uncoordinated tenant-database row SHALL NOT count as the boundary.

#### Scenario: A worker reaches the boundary first
- **WHEN** its tenant-first transaction commits `provider_submitting` before a freeze transaction
- **THEN** later fencing SHALL classify that operation as an in-flight uncertain provider window requiring snapshot-based reconciliation

#### Scenario: A safety gate commits first
- **WHEN** suspension, deletion, expiry, or recovery hold changes the tenant authority before the worker's boundary transaction
- **THEN** the worker's compare-and-swap SHALL fail and no provider request SHALL be sent

### Requirement: Isolate external side effects with outbox and execution ledgers

User actions that can call SF, Kuaimai, Xianyu, SMS, or another external provider MUST first atomically persist their authorized intent, immutable technical context, outbox or job execution, idempotency key, and safe audit reference; provider network calls SHALL occur only after that transaction commits and outside open business-database transactions.

#### Scenario: A cross-database or provider action is authorized
- **WHEN** its final authorization transaction succeeds
- **THEN** the system SHALL durably enqueue the exact immutable revision and resource references needed by the worker before returning or performing the external call

#### Scenario: The authorization transaction rolls back
- **WHEN** CSRF, OTP, tenant gate, target revision, outbox, or audit persistence fails
- **THEN** the system SHALL perform no external side effect and SHALL leave no executable orphan intent

#### Scenario: Provider I/O is slow or fails
- **WHEN** the worker performs the network request
- **THEN** it SHALL release tenant database transactions and connections before I/O and persist the result afterward in a separate bounded transaction

### Requirement: Retry only provably safe operations

Automatic retries MUST be bounded and allowed only when the operation is provably not submitted, the provider explicitly rejected it, or a stable provider idempotency and query contract proves repetition safe; ambiguous non-idempotent results SHALL enter `needs_review` or `recovery_review` rather than being replayed.

#### Scenario: A provider explicitly rejects a request before creating a side effect
- **WHEN** retry policy classifies the failure as transient and the stable idempotency key remains current
- **THEN** the normal job MAY retry within its configured attempt limit

#### Scenario: Physical printing times out after submission
- **WHEN** the system cannot prove that no sheet was printed
- **THEN** the print execution SHALL enter `needs_review`, SHALL NOT auto-retry, and a user SHALL have to verify the outcome before creating a new reprint job

#### Scenario: A retained historical credential is missing or invalid
- **WHEN** reconciliation cannot authenticate the exact credential revision recorded by the execution ledger
- **THEN** the operation SHALL fail closed into a stable review state and SHALL NOT fall back to a current or default integration credential

### Requirement: Commit batch provider work per item

Batch workflows that can create multiple external side effects MUST create and commit a distinct pending execution with a unique idempotency key for each item before provider calls, and SHALL persist each result in its own short transaction rather than wait to commit the entire batch.

#### Scenario: A batch SF shipment crashes after some items succeed
- **WHEN** several rental executions have already received provider results but the worker stops before finishing the batch
- **THEN** their individual waybill, account, binding, sender, and credential-revision snapshots SHALL remain committed
- **AND** recovery SHALL query the local/provider ledger by the same stable order identity instead of blindly creating those waybills again

### Requirement: Resume scheduling without replaying unsafe missed work

After suspension or disaster-recovery release, the scheduler MUST generate ordinary periodic read or synchronization work only from the current schedule point and SHALL NOT bulk-return old jobs to pending or replay every missed cycle; blocked user-triggered side effects and uncertain executions SHALL require explicit review or a newly authorized job.

#### Scenario: An active tenant is resumed
- **WHEN** DML routing is safely republished and the effective tenant gate becomes active
- **THEN** future periodic work SHALL use the new access version, while old blocked executions retain their terminal or review states

#### Scenario: Resume resolves to expired
- **WHEN** the current subscription time makes the resumed tenant expired
- **THEN** the worker SHALL continue to deny normal business-job leases

#### Scenario: A missed job is still safely actionable
- **WHEN** `not_after` has not passed, all preconditions remain true, and the action is provably idempotent and unsubmitted
- **THEN** the system MAY create a new current-run/current-access-version job rather than revive the stale job

### Requirement: Coordinate Xianyu synchronization without duplicate provider calls

The background process MUST schedule one tenant-level Xianyu alert synchronization every 180 seconds for each eligible active tenant using deterministic staggering and a stable tenant/connection-set time-bucket idempotency key; each job SHALL freeze the complete active connection/revision set, and manual refresh SHALL cover all active shops while reusing any scheduled or manual synchronization already in flight.

#### Scenario: A tenant has multiple Xianyu connections
- **WHEN** its tenant-level synchronization runs
- **THEN** the worker SHALL record each connection result independently, retain prior successful alerts for a failed connection, and update the tenant aggregate snapshot revision only from persisted results
- **AND** alert identity and replacement SHALL be scoped by connection UUID plus order number rather than a tenant-global bare order number

#### Scenario: A user requests refresh during an in-flight sync
- **WHEN** an Admin or Operator submits the high-priority refresh action
- **THEN** the API SHALL return `202` with the existing job ID and snapshot revision instead of initiating another provider call

#### Scenario: A page periodically refreshes visible alerts
- **WHEN** the page is visible on its three-minute interval
- **THEN** it SHALL read only the tenant-database alert summary and SHALL NOT invoke Xianyu directly

### Requirement: Separate system cleanup from ordinary business jobs

D54 replacement cleanup and D58 recovery cleanup MUST run through a system-only control outbox and fenced janitor that is distinct from `background_jobs`; platform and tenant users SHALL NOT view per-attempt cleanup resources, cancel, replay, edit payloads, or create these cleanup operations.

#### Scenario: Replacement issuance leaves provisional resources
- **WHEN** the winning replacement transaction records an eligible provisional schema, account, route, or task to remove
- **THEN** it SHALL create exactly one system cleanup outbox tied to the source and replacement generation, idempotency key, and fencing lease

#### Scenario: There are no provisional resources
- **WHEN** current locked evidence proves that the source has no schema, account, route, or task
- **THEN** the system SHALL record the approved no-resource disposition and SHALL NOT create an empty cleanup job

#### Scenario: Janitor cleanup fails or crashes
- **WHEN** a cleanup step cannot complete
- **THEN** the same fenced system operation SHALL remain safely retryable, emit aggregated operational alerts and immutable audit evidence, and SHALL NOT block the replacement code or revive the old attempt, code, route, or worker

### Requirement: Bound and audit normal job operations

Normal business jobs MUST use finite retry and dead-letter policies, priority/type scheduling, safe structured correlation, and an explicit operations allowlist for any platform replay or cancellation; system cleanup SHALL remain outside that allowlist.

#### Scenario: A normal job exhausts its retries
- **WHEN** its bounded attempts fail without a safe terminal business result
- **THEN** it SHALL enter dead-letter or review state with tenant, job, request, and correlation identifiers but without OTPs, Secret plaintext, customer PII, or raw provider payloads

#### Scenario: An operator replays an allowlisted normal job
- **WHEN** the job type permits replay and current tenant authority plus idempotency checks pass
- **THEN** the platform SHALL record the actor, action, reason, source job, and result in audit and SHALL NOT permit payload mutation
