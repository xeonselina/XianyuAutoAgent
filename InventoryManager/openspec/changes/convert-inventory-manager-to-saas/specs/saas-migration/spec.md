## ADDED Requirements

### Requirement: Active OpenSpec changes are reconciled in the SaaS implementation
The migration program MUST apply D12's recorded classification as ordinary project work: finish and archive the unified SF express-type change and completed rental-damage-notes change, pause the legacy A4 standalone shipping-order and legacy scan-based shipping workflow changes, and rebase every retained capability onto tenant routing, warehouses, durable jobs, unified overlap rules, and current integration revisions before it joins the cutover implementation. D63 cancels every code, schema, and core-module migration freeze, freeze exception, unfreeze, and post-cutover 48-hour freeze process.

#### Scenario: A retained active change still uses a global provider credential
- **GIVEN** an unarchived retained change is otherwise functionally complete
- **WHEN** its SaaS compatibility review finds process-global credentials or a synchronous provider side effect
- **THEN** it is not archived or included unchanged in the cutover
- **AND** its delta/tasks are rebased to the confirmed tenant integration and durable-job boundaries

### Requirement: The migration uses an expand-to-contract sequence
The system MUST migrate in the ordered phases baseline and schedule planning, control and tenant schema expand, idempotent backfill and verification, application enforcement, database/job enforcement, project-complete scheduling and rehearsal, and contract cleanup. Each phase SHALL have a recorded input, reversible boundary, ordinary checklist, and error/retry action. D64 removes phase review checkpoints, candidate signatures/receipts/evidence digests, and hard release decisions; a failed check remains unchecked, is fixed, and is rerun. Phase 0 MUST use facts independently available from the current repository/deployment or external account qualification and MUST NOT require artifacts produced only by later schema, root-key, integration, monitoring, backup, or restore implementations. Contract cleanup MUST NOT begin while a supported reader/writer or rollback target still depends on legacy fields or configuration.

#### Scenario: Backfill verification fails for one tenant
- **GIVEN** expand completed but a row, relationship, identity, or digest reconciliation differs
- **WHEN** the ordinary backfill checklist is run
- **THEN** application enforcement does not begin for that tenant
- **AND** rerunning the same migration idempotency key cannot duplicate records or mask the difference

#### Scenario: Phase 0 is recorded before later components exist
- **GIVEN** Core root-key files, encrypted secret revisions, health endpoints, monitoring adapters, the NAS wrapper, and restore-test outputs do not yet exist
- **WHEN** Phase 0 records current baselines, independently available provider/account capabilities, owners, and the later work plan
- **THEN** Phase 0 is complete without fabricating those later artifacts
- **AND** their implementation and tests remain ordinary project checklist items before `project_complete_at`

### Requirement: Project completion deterministically schedules rehearsal
The migration program MUST directly record `project_complete_at=T` after the complete project implementation, default-tenant migration/backfill/rollback tools, and all necessary tests that can run without the first production-scale rehearsal are complete. This timestamp SHALL require no candidate signature, receipt, evidence digest, phase review, release decision, or freeze. It explicitly excludes the first production-scale rehearsal itself, actual cutover, post-cutover 48-hour observation, and contract cleanup. `earliest_rehearsal_at` SHALL equal T plus 168 hours, and the first production-scale migration rehearsal SHALL use the first available operating window at or after that time.

#### Scenario: The project implementation and necessary tests complete
- **GIVEN** the whole project implementation, default-tenant migration tools, and all necessary pre-rehearsal tests are checked complete
- **WHEN** the project records completion at UTC time T
- **THEN** `project_complete_at` equals T and `earliest_rehearsal_at` equals T plus 168 hours
- **AND** no signature, receipt, evidence digest, exception chain, or code/schema hold is created

#### Scenario: Migration-affecting implementation changes during the seven-day interval
- **GIVEN** `project_complete_at=T` was recorded and a later implementation change can affect migration results
- **WHEN** the change is completed and its related migration, rollback, isolation, and API contract tests are rerun
- **THEN** `project_complete_at` is updated to the new completion time and 168 hours is recalculated from it
- **AND** normal development continues without a special exception, while D61 is not extended

#### Scenario: The first available operating window is later than the earliest time
- **GIVEN** the current `project_complete_at` remains valid and T plus 168 hours has passed
- **WHEN** no usable operating window is available at that exact time
- **THEN** the rehearsal uses the next available window
- **AND** the delay creates no code hold and does not extend D61

### Requirement: Temporary legacy credential acceptance is bounded and non-transferable
The migration program MUST treat D61 as a temporary risk acceptance only for the already exposed legacy database account, existing default-tenant SF credentials, and existing Kuaimai credentials. The user confirmed only that acceptance is bounded; the current operations policy v1 uses 30 periods of 24 hours as a conservative default and per-window maximum, not as a verbatim user-selected duration. Each window SHALL be explicitly reviewed, MAY be shorter, SHALL never renew automatically, SHALL end immediately on a recorded trigger or missed review, and SHALL end no later than the first production-scale rehearsal. It MUST NOT assert that the values were unexposed, waive scanning/network/provider/monitoring/cleanup records, authorize reuse for any Core control/root/backup/provisioner/tenant-derived account or future tenant, or cover Xianyu and other credential classes.

#### Scenario: The current bounded review is missed
- **GIVEN** one of the three legacy credentials remains authoritative under D61
- **WHEN** its current policy window expires without a new explicit owner review and record refresh
- **THEN** the acceptance is expired
- **AND** the credential MUST be rotated or revoked before credential-dependent work continues

#### Scenario: The first production-scale rehearsal begins
- **GIVEN** a D61 exception was valid during implementation
- **WHEN** the D64 rehearsal start is reached
- **THEN** the legacy database account is no longer a Core runtime identity and the old SF/Kuaimai values are revoked or rotated
- **AND** only least-privilege database identities and newly validated encrypted provider revisions may be used by the rehearsal candidate

### Requirement: The existing business schema becomes the default tenant in place
The migration MUST register the original business schema as one immutable default tenant/database identity without copying the whole database or adding `tenant_id` to every business table. It SHALL require explicitly supplied default-tenant display identity and first Admin canonical phone, create a ready or runtime-restricted default warehouse from existing sender data, assign non-secret provider configuration ownership to that tenant, and preserve business primary keys, relationships, row counts, and audited amounts. D61-covered legacy SF/Kuaimai values MUST NOT be read, copied, hashed, mechanically encrypted, or wrapped as Core revision 1/current revisions. Only provider-rotated replacement values that are freshly submitted and successfully validated may create the new revision 1 before first rehearsal. Under D68, recognized legacy shipping, tracking, lifecycle, and print-occurrence facts SHALL instead enter structurally separate `legacy_unattributed` read-only snapshots that contain no integration, account, binding, credential-revision, provider-order, printer, or provider-task authority.

#### Scenario: Default tenant migration is rerun with the same inputs
- **GIVEN** an earlier attempt stopped after any supported intermediate step
- **WHEN** the same migration idempotency key and parameters are rerun
- **THEN** it converges on the same tenant/database UUID, identity, Admin, route, warehouse, and migration records
- **AND** it does not clone the schema, duplicate memberships, or increment access versions without a transition

#### Scenario: The importer encounters D61 legacy SF or Kuaimai values
- **GIVEN** a legacy environment, configuration, log, or history source contains a D61-covered value
- **WHEN** the default-tenant migration imports provider ownership
- **THEN** it may create only non-secret `unconfigured/pending` connection or account metadata and creates no secret revision, current pointer, or claim from that value
- **AND** a separate provider-rotated, freshly submitted, successfully validated replacement is required to create revision 1

#### Scenario: The importer encounters old shipment and print history
- **GIVEN** a legacy rental or audit row proves a lifecycle, tracking number, or print-occurrence fact but cannot prove the exact historical credential revision
- **WHEN** the default-tenant backfill runs under the approved D68 adapter
- **THEN** it SHALL create or replay only the matching `legacy_unattributed` read-only snapshot and preserve its source identity and digest
- **AND** it SHALL create no Core shipment, provider attempt, print job, credential revision, provider order, printer task, or provider call from that history

### Requirement: Default tenant receives one fixed long-term migration grant
The migration MUST create the default tenant's initial subscription from the immutable Core plan revision bundled with that migration, with `member_seats = 10` and an exact duration of 36,500 days of 24 hours. The final control-database transaction SHALL calculate expiry from database current time and append one immutable `migration_grant` subscription event uniquely bound to the default tenant UUID, database UUID, initial baseline, and migration idempotency key; it MUST NOT accept a duration/expiry deployment parameter, create a perpetual-subscription state, consume a redemption code, or bypass normal lifecycle and recovery state checks.

#### Scenario: Initial migration grant is committed
- **GIVEN** schema identity, Admin, route, warehouse, credentials, and data reconciliation have passed for the default tenant
- **WHEN** the final default-tenant migration transaction commits at database time T
- **THEN** the subscription uses the migration artifact's bundled immutable Core plan revision and entitlement digest
- **AND** `expires_at` equals T plus exactly 36,500 days
- **AND** one immutable `migration_grant` event records the calculation base, duration, tenant/database identity, and migration source

#### Scenario: Migration grant is retried after response loss
- **GIVEN** the initial grant already committed but the migration client did not receive the response
- **WHEN** the same default tenant, database, initial baseline, and idempotency key are retried
- **THEN** the migration returns the original subscription and event
- **AND** it does not add another 36,500 days or create a second grant

#### Scenario: Default tenant remains subject to runtime safety state checks
- **GIVEN** the default tenant has the long-term migration grant
- **WHEN** platform suspension, controlled deletion, recovery hold, or a D53 adjustment applies
- **THEN** the ordinary confirmed lifecycle rule takes effect
- **AND** default-tenant identity or long expiry does not create an exemption

### Requirement: Business backfill is ordered and idempotent
The migration MUST backfill default warehouse and device ownership before structured logistics snapshots, then accessory types/units before requests/links/events, then non-secret provider metadata before D68 `legacy_unattributed` shipment/print snapshots; newly validated provider connections/account revisions/bindings remain separate inputs for new Core operations. Every transform SHALL have a stable source identity, idempotency key, negative/orphan checks, and reversible expand-period mapping; legacy quantity, child-rental, global-credential, or shipment facts MUST NOT be double-counted after enforcement.

#### Scenario: Accessory backfill restarts midway
- **GIVEN** some legacy accessories have generated units and unfinished child rentals have generated requests/links
- **WHEN** the backfill resumes after failure
- **THEN** each source produces at most one intended unit/request/link/event lineage
- **AND** source, target, holder, warehouse, and unresolved counts reconcile before legacy readers are disabled

#### Scenario: Legacy history backfill restarts after committed snapshots
- **GIVEN** some source rentals or print audits already produced `legacy_unattributed` snapshots
- **WHEN** the same manifest and historical boundary rerun the backfill
- **THEN** each source identity replays the exact snapshot without creating a second row
- **AND** any changed source digest, unmatched count, Core credential reference, or executable provider/print record fails the phase before reconciliation passes

### Requirement: Cutover has one safe rollback boundary
The migration MUST stop Web writes, schedulers, workers, and provider submissions during the production maintenance window and record the exact point at which tenant-aware writes become authoritative. Before that point the tested rollback may restore the old application without reverse data movement; after that point rollback SHALL use only a compatible tenant-aware version or forward fix and MUST NOT restart the old global writer.

#### Scenario: A required check differs before tenant-aware writes
- **GIVEN** cutover is inside the maintenance window and the old-writer boundary has not been crossed
- **WHEN** a critical migration, isolation, or smoke check reports an error
- **THEN** operators execute the rehearsed old-application rollback and keep new writers disabled
- **AND** the run records the failure and data reconciliation evidence

#### Scenario: A defect is found after tenant-aware writes begin
- **WHEN** operators select a recovery action
- **THEN** only a compatible tenant-aware rollback or forward fix is allowed
- **AND** the legacy global database account, scheduler, or provider configuration is not re-enabled

### Requirement: Schema drift prevents mixed unsafe writers
The system MUST track the expected and actual schema generation/digest for the control database, tenant template, and every active/protected tenant database. CI and fleet migration SHALL detect missing migrations, incompatible model/session use, untrusted database selection, and a tenant that failed or drifted; the affected migration remains incomplete and is fixed and retried rather than routing around the tenant or running mixed unsafe writers.

#### Scenario: One tenant database misses an enforced constraint
- **GIVEN** most tenant databases match the target generation
- **WHEN** the fleet verifier finds one active tenant with a different digest
- **THEN** the checklist records the mismatch and keeps that database held
- **AND** no generic DML account or compatibility switch bypasses the drift

### Requirement: The test matrix proves isolation and state-machine safety
The release MUST include automated positive and negative tests for two-tenant database routing/grants, cache and file isolation, tenant/platform identity separation, sessions/RBAC/CSRF, OTP limits and action binding, invitations and ten-seat races, registration/code/replacement races, lifecycle priority, warehouses/accessories/relay, immutable provider revisions and side-effect recovery, backup/tombstone/recovery behavior, and migration idempotency. Tests SHALL inject crashes and response loss at every committed external-effect boundary.

#### Scenario: Provider succeeds but local response is lost
- **GIVEN** a shipment or print submission reached the provider
- **WHEN** the worker crashes before recording a success response
- **THEN** the test proves that replay uses the persistent operation identity and the confirmed reconciliation rule
- **AND** an unknown print result is not automatically submitted again

#### Scenario: A database test targets the reachable production instance
- **GIVEN** the local test host can reach both the production business schema and `inventory_management_test` on the same MySQL instance
- **WHEN** a test requests a database connection
- **THEN** production access is limited to explicitly enabled single-statement non-locking reads through an account proven to have only `SELECT/SHOW VIEW` on the exact production schema
- **AND** every write, migration, fixture reset, or destructive fault injection is rejected unless `ALLOW_REAL_TEST_DATABASE=true`, the selected schema is exactly `inventory_management_test`, and its current grants and possibly drifted schema have been observed first
- **AND** every database-backed test runs serially against that existing test schema without creating a database, account, grant, or disposable MySQL instance
- **AND** a global DBA credential is accepted only through the separate test opt-in while statement guards reject schema switching, instance/account mutation, and explicit cross-schema writes

### Requirement: Performance and payload budgets are ordinary test tasks
The project MUST compare booking, Gantt, edit, search, list, and mutation flows against the recorded Phase 0 HTTP, SQL, connection, latency, and compressed-payload baselines. It SHALL test constant-bounded core fan-out at the recorded fixture scale, no deep repeated DTO/PII, and p95 overhead against the current 20 percent regression threshold. A mismatch remains an ordinary unchecked task to optimize and rerun or to record with its reason; it creates no separate decision checkpoint.

#### Scenario: Dynamic tenant routing exceeds the latency budget
- **GIVEN** functional and isolation tests pass
- **WHEN** representative load shows a key route more than 20 percent slower than baseline
- **THEN** the ordinary task remains unchecked for optimization and rerun or a recorded capacity disposition
- **AND** the regression is not hidden by browser caching of inventory facts

### Requirement: Production provider and operations checks remain ordinary tasks
The project checklist MUST verify Tencent Cloud enterprise/SMS qualification, signature/templates/carrier filing with controlled real numbers, real SF delivery-time capability, versioned monitoring policy and every notification channel, least-privilege MySQL/NAS/CAM access, backup freshness, offline root-key recovery, and a successful off-host full recovery exercise. A failed item is fixed or completed and rerun as an ordinary task, without a separate review checkpoint. Production runtime MUST NOT substitute fixed OTPs, fake providers, unverified backups, same-host restore, or untested alert routes.

#### Scenario: Application tests pass but SMS qualification is incomplete
- **WHEN** the ordinary production-readiness checklist is run
- **THEN** registration, login, and action-bound OTP production rollout remains blocked
- **AND** a non-production fake-provider result does not satisfy the real-number task

### Requirement: Legacy surfaces are removed only after negative verification
The contract phase MUST remove old global database/provider accounts, scheduler paths, compatibility routes, OCR/contract/standalone-document surfaces, old static branding, global API-key paths, legacy accessory contributors, and migration flags only after all supported clients and jobs use the new contracts. Release evidence SHALL include route/config/bundle/secret scans and negative calls proving those surfaces cannot execute or reappear after restore.

#### Scenario: Old configuration remains in an image
- **GIVEN** runtime code no longer references a global provider environment variable
- **WHEN** the production image and deployment bundle scan still finds a real or accepted fallback value
- **THEN** the contract task remains unchecked
- **AND** operators remove the fallback and rerun the scan, while any D61-covered value must also have been rotated or revoked no later than the first production-scale rehearsal
