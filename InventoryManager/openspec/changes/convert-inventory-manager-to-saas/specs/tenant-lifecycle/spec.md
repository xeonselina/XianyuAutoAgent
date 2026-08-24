## ADDED Requirements

### Requirement: Effective tenant access is reduced in one control-plane gate
The system MUST derive effective access from the tenant lifecycle state, subscription expiry, suspension, deletion request, recovery hold/run, membership, session/auth version, and requested action. Every browser request, worker claim, and provider-side-effect transition SHALL use the same current control-plane facts or an explicit version fence; a UI allowlist MUST NOT override a final transactional denial.

#### Scenario: A stale request loses access after a lifecycle transition
- **GIVEN** a request authenticated before the tenant access version changed
- **WHEN** suspension, deletion freeze, recovery hold, membership change, or security action commits first
- **THEN** the request fails its final access-version or lifecycle check
- **AND** it cannot write tenant data, claim a job, or begin a provider side effect

### Requirement: Platform suspension immediately freezes tenant effects
The system MUST allow an authorized platform administrator with a fresh factor to suspend an eligible tenant only after supplying a reason and confirmation. The suspension transaction SHALL increment the tenant access version, revoke or invalidate existing sessions, prevent new job claims and provider side effects, and record an immutable audit event without extending or otherwise changing the subscription period.

#### Scenario: Suspended tenant cannot continue queued provider work
- **GIVEN** a tenant has browser sessions and queued shipping or print jobs
- **WHEN** platform suspension commits
- **THEN** business access and new job claims are denied immediately
- **AND** workers holding older access versions cannot cross into a new provider-submitting boundary
- **AND** old jobs are not blindly replayed on later recovery

#### Scenario: Suspended member sees only the confirmed allowlist
- **GIVEN** a valid member signs in to a suspended tenant
- **WHEN** the member accesses the application
- **THEN** an Operator can only view the suspension explanation and log out
- **AND** an Admin can additionally use the confirmed account-security allowlist
- **AND** neither role can renew, unbind a SF account, or use business and integration routes

### Requirement: Resume re-evaluates current subscription state
The system MUST make resume a separate freshly authorized platform action. Resume SHALL clear only the completed suspension, issue a new access version, and reduce the tenant against the database's current subscription expiry so that the result is `active` or `expired`; it MUST NOT extend service time or revive old sessions, OTPs, invitations, intents, jobs, or provider attempts.

#### Scenario: Subscription expires during suspension
- **GIVEN** a tenant was active when suspended and its expiry passes during suspension
- **WHEN** an authorized platform administrator resumes it
- **THEN** it enters the expired renewal loop rather than active business access
- **AND** no previously queued provider job is automatically resumed

### Requirement: Tenant deletion uses review and a cooling-off state machine
The system MUST require a tenant Admin's action-bound deletion OTP to create a single non-terminal deletion request, platform review, and a 30-day cooling-off period. A valid Admin may cancel during the allowed cooling-off window with a distinct action-bound OTP; every transition SHALL use request revision, execution generation, lease fencing, and tenant access-version checks.

#### Scenario: Approved deletion freezes writes but remains cancellable during cooling off
- **GIVEN** platform review approves a deletion request
- **WHEN** the request enters cooling off
- **THEN** tenant DML credentials and business access are locked under a new unpublished/published generation boundary
- **AND** an authorized cancellation with the matching current revision can restore an evaluated active-or-expired state through a new credential generation
- **AND** old credentials and sessions are not reused

#### Scenario: Stale cancellation loses to commit
- **GIVEN** a cancellation challenge was issued before the deletion executor entered `committing`
- **WHEN** the stale cancellation arrives after the commit boundary
- **THEN** its CAS fails and the challenge cannot reopen or mutate the deletion

### Requirement: Destructive deletion waits for permanent offsite evidence
The system MUST append an immutable, privacy-minimized deletion tombstone before dropping tenant data and SHALL wait for authenticated acknowledgement that the matching ledger sequence/hash is present in the offsite backup set. Only the fenced deletion executor may then release every active or reserved global provider-account claim with linked claim events, isolate or terminate provider operations, drop tenant routes/accounts/schema, minimize control-plane PII, and mark deletion complete.

#### Scenario: Offsite acknowledgement is missing
- **GIVEN** a deletion has reached the destructive preparation stage
- **WHEN** no valid NAS/offsite acknowledgement matches the current tombstone sequence and hash
- **THEN** the request remains `awaiting_offsite_ack`
- **AND** no tenant schema, database account, route, provider account, integration secret, or current global claim is deleted

#### Scenario: Completed deletion cannot be undone by foreign keys or restore
- **GIVEN** destructive deletion completed
- **WHEN** owner rows are minimized or removed, or an older backup is later restored
- **THEN** the permanent tombstone and claim-event chain remain independent of deletable owner rows
- **AND** provisioning and recovery refuse to republish the deleted tenant/database UUID

### Requirement: Identity reuse waits for completed deletion
The system MUST retain the tenant's user, membership, and canonical phone ownership through review, cooling off, and destructive execution. Only a fully completed deletion with tombstone and cleanup evidence SHALL release the phone for a future OTP registration or invitation; no platform action may bypass old-phone verification or directly reassign a living membership.

#### Scenario: Phone cannot be reused during deletion
- **GIVEN** a tenant deletion is pending, cooling off, committing, awaiting acknowledgement, dropping, or failed
- **WHEN** the same canonical phone attempts registration in another tenant
- **THEN** identity coordination rejects the new membership
- **AND** it does not disclose the old tenant or deletion state

### Requirement: Restore places affected scope under a new recovery hold
The system MUST create a new recovery epoch/run before serving any scope restored from an older control database, full host image, or tenant schema. It SHALL invalidate or quarantine pre-restore sessions, challenges, pending invitations, sensitive intents, unfinished registrations, job leases, and provider operations; restore-time active/reserved codes become `recovery_revoked`, and affected tenants remain held until their coverage and immutable identifiers are reconciled.

#### Scenario: Application starts before recovery normalization completes
- **GIVEN** restored data is present but recovery marker, run, coverage digest, or normalization is absent or inconsistent
- **WHEN** a tenant or worker route is requested
- **THEN** the affected scope fails closed
- **AND** no business connection, credential publication, code operation, or external side effect is allowed

### Requirement: Recovery release is tenant-by-tenant and fail closed
The system MUST allow a platform administrator to review and release at most one covered tenant per action after database identity, schema generation, access accounts, routes, jobs, invitations, registrations, codes, claims, tombstones, and provider-operation dispositions agree. Audit or least-privilege account convergence failure SHALL keep that tenant held, and no release may recreate the removed external API or any old global API key.

#### Scenario: One tenant passes while another remains inconsistent
- **GIVEN** a recovery run covers tenants A and B
- **WHEN** A has complete evidence and B has a route or claim mismatch
- **THEN** an authorized action may release A only
- **AND** B remains held without borrowing A's evidence or access state

### Requirement: Recovery run completion requires external evidence
The system MUST mark a host-recovery run completed only after coverage is closed and either one safely released active tenant passes an end-to-end smoke test, or, when no eligible active survivor can be safely released, a DR-only scratch tenant passes and is destroyed with evidence. New-origin external HTTPS health success SHALL be the external completion signal; the four-hour recovery target is a reference objective, not a substitute for these gates.

#### Scenario: No active survivor is eligible for safe release
- **GIVEN** coverage is complete but all restored production tenants must remain held or expired/deleted
- **WHEN** operators create a DR-only scratch tenant, run the required smoke checks, destroy it, and obtain external new-origin health evidence
- **THEN** the run may become completed with the scratch and destruction evidence linked
- **AND** no production tenant is falsely marked released

