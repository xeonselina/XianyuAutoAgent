## ADDED Requirements

### Requirement: Operational telemetry is low-cardinality and privacy safe
The system MUST emit structured logs with request, trusted tenant, actor, route, job, and correlation identifiers while redacting PII and secrets. Metric dimensions and alert bodies SHALL use an allowlist of environment, component, signal, severity, region, and low-cardinality result classes; tenant, user, phone, request, job, device, rental, warehouse, raw URL, provider request ID, and free text MUST NOT become public metric dimensions or notification content.

#### Scenario: Provider error contains customer data
- **GIVEN** a provider response includes a phone number, address, account number, or free-form customer text
- **WHEN** the application records an operational failure
- **THEN** logs redact the sensitive fields
- **AND** the metric and alert contain only an approved aggregate result class and authenticated internal link

### Requirement: Core monitoring has exactly the confirmed three signal layers
The system MUST monitor production through Tencent Cloud CVM/Agent base signals, off-host HTTPS probes, and a small set of application/worker operational states. Core SHALL NOT require Managed Prometheus, Grafana, a general metrics scraper, a time-series database, a public `/metrics` endpoint, or a tracing backend.

#### Scenario: CVM Agent stops reporting
- **GIVEN** the host remains reachable but the official monitoring Agent is missing or stale
- **WHEN** the missing-data window elapses
- **THEN** the monitoring state is degraded and alerts according to policy
- **AND** absent measurements are not rendered as healthy

### Requirement: External health separates serving from background degradation
The system MUST expose fixed, no-store, non-tenantized `/health/external` and `/health/monitor` endpoints with independent small connection and rate budgets. The external endpoint SHALL cover DNS/TLS/Nginx/Web, a minimal control-database read, and host-recovery completion; the monitor endpoint SHALL cover worker/evaluator heartbeat and latched notification-delivery failure. Neither endpoint may query tenant databases, execute a provider call, mutate business state, reveal versions or internal identifiers, or be satisfied by CDN cache.

#### Scenario: Worker stops while Web remains available
- **GIVEN** DNS, TLS, Nginx, Web, and the control database are serving but worker heartbeat is stale
- **WHEN** off-host probes run
- **THEN** `/health/external` remains successful
- **AND** `/health/monitor` fails as P2
- **AND** the condition does not start a host-disaster-recovery run

#### Scenario: Host restore is still reviewing
- **GIVEN** the platform recovery UI is reachable on a new host but the current run is not completed
- **WHEN** the external probe calls `/health/external`
- **THEN** it receives the fixed failure response
- **AND** no held tenant count or recovery detail is disclosed

### Requirement: Monitoring policy and notifications are versioned release inputs
The system MUST reject a production monitoring policy that omits probe quorum/timeouts, missing-data windows, resource thresholds, heartbeat staleness, queue age/failure rules, provider aggregation windows, backup/cloud-sync age, notification retry/latch behavior, or recovery hysteresis. P1 SHALL notify verified maintainer phone, SMS, and email channels continuously; P2 SHALL notify verified personal WeChat and email, and recovery notices SHALL follow the original channels.

#### Scenario: Notification delivery fails
- **GIVEN** an event requires a Tencent Cloud custom message
- **WHEN** real delivery fails or its result is unknown after bounded retry
- **THEN** the delivery ledger atomically latches `delivery_unhealthy`
- **AND** `/health/monitor` fails so the independent P2 probe path can alert
- **AND** only a later real event or explicit successful test clears the latch

### Requirement: Backups are consistent, complete artifacts
The system MUST create a coordinated full backup of the control database and all active or protected tenant databases under one fleet/DDL lease. Each run SHALL write dumps, a manifest, schema mapping, required root-key versions and fingerprints, tombstone-head reference, checksums, and completion metadata into a partial location, verify them, and atomically publish the artifact only after every required component succeeds; the platform root key itself MUST NOT be included.

#### Scenario: One tenant dump fails
- **GIVEN** a backup run successfully dumps the control database and several tenant databases
- **WHEN** another required tenant dump or checksum fails
- **THEN** the set remains incomplete and is never published as the latest restore point
- **AND** NAS/cloud sync does not treat partial files as a completed artifact

### Requirement: NAS pulls backups with least privilege and fixed retention
The system MUST make the home NAS initiate the hourly transfer through a restricted forced-command SSH identity; the production host SHALL NOT mount the NAS or hold NAS write credentials. The NAS SHALL verify manifest/checksums before acknowledging success and retain 48 hourly, 30 daily, and 12 monthly completed full sets.

#### Scenario: Backup acknowledgement becomes older than 90 minutes
- **GIVEN** no newly verified NAS backup acknowledgement has arrived for more than 90 minutes
- **WHEN** operational policy evaluates backup freshness
- **THEN** a P1 condition is raised even if an application-local dump file exists
- **AND** a cloud-sync acknowledgement is not substituted for backup success

### Requirement: Cloud-drive replication and tombstone ledger are independent
The system MUST let the NAS's existing capability copy only verified completed backup sets to cloud drive and report cloud-sync success separately. The permanent deletion-tombstone ledger SHALL be independently replicated, append-only, integrity checked, and applied before restored tenant routes or accounts are created; application and cloud hosts MUST NOT receive cloud-drive credentials.

#### Scenario: Dump succeeds but cloud sync is stale
- **GIVEN** NAS has acknowledged a fresh verified backup but its cloud-drive sync heartbeat is stale
- **WHEN** monitoring evaluates the two signals
- **THEN** backup freshness remains successful and cloud-sync reports an independent P2
- **AND** neither signal infers the other's success

### Requirement: Root key recovery is separated from database recovery
The system MUST keep each required platform-root-key version in an offline recovery path that does not share the sole host, archive, or recovery password with database backups. Restore tooling SHALL validate the manifest's key fingerprints before decrypting or publishing any account or provider secret and SHALL fail closed for an unavailable or mismatched version.

#### Scenario: Database backup is intact but a required root version is missing
- **WHEN** restore validates a manifest that references the unavailable version
- **THEN** tenant routes, database accounts, codes, platform factors, and provider credentials remain unavailable
- **AND** the tooling does not silently derive a new key or discard encrypted history

### Requirement: Restore uses a version-locked wrapper and staging import
The system MUST permit production full, control, or tenant-only restore only through the root-owned version-locked wrapper with a verified manifest and explicit schema allowlist. Full/control restore SHALL rotate the external marker before the first database change and enter disaster-recovery mode; tenant-only restore SHALL install a tenant hold and lock all DML generations first. Old dumps MUST be imported into a non-routable staging MySQL and validated before controlled cutover.

#### Scenario: Operator tries to import an all-databases dump directly
- **GIVEN** production routes are otherwise available
- **WHEN** an unsupported application or migration command attempts direct import
- **THEN** the supported tooling refuses the operation
- **AND** no restored schema becomes routable or receives a tenant database account

### Requirement: Recovery evidence is durable and rehearsal based
The system MUST preserve versioned images/scripts, monitoring configuration, restore tooling, root-key access instructions, NAS access, and runbooks outside the failed host. Before first production release it SHALL complete a full recovery exercise on a genuinely different host/origin and retain coverage, timing, tenant-or-scratch smoke, destruction when applicable, external probe, notification, and follow-up evidence; Core provides best-effort service with an hourly restore-point objective and four-hour internal recovery reference, not a numeric SLA or compensation promise.

#### Scenario: Recovery exceeds four hours but remains unsafe to release
- **GIVEN** a rehearsal passes the four-hour reference while a coverage or identity check still fails
- **WHEN** operators decide whether to complete the run
- **THEN** the run remains fail closed until the evidence gate passes
- **AND** the overrun creates an improvement item rather than an automatic release or compensation state

