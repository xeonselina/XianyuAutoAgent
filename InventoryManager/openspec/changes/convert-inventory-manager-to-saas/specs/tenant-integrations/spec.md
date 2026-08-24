## ADDED Requirements

### Requirement: Provider connections use immutable encrypted secret revisions
The system MUST store SF, Xianyu, and Kuaimai credentials as tenant-owned integration connections with immutable secret revisions. Each revision SHALL use a new record-purpose HKDF context, random 12-byte nonce, versioned AES-256-GCM envelope, authenticated tenant/provider/integration semantics, and a lifecycle pointer switched only after provider validation; plaintext, nonces, ciphertext, and full credentials MUST NOT appear in list responses, logs, metrics, or audit text.

#### Scenario: New credentials fail provider validation
- **GIVEN** an integration has a working current revision
- **WHEN** an Admin submits a new bundle that fails validation
- **THEN** the pending revision does not become current
- **AND** the previous immutable revision remains available for new actions
- **AND** no old ciphertext is overwritten

#### Scenario: Platform root key rotates
- **GIVEN** a historical shipment references a business credential revision
- **WHEN** the authorized global rotation rewrites its encrypted envelope
- **THEN** the revision UUID and business semantics remain unchanged while envelope generation and audit evidence advance
- **AND** the rotation cannot masquerade as a credential content update

### Requirement: Provider settings require action-bound Admin verification
The system MUST require an active tenant Admin, current lifecycle eligibility, expected revision, and an unconsumed D48 OTP bound to the tenant, actor, action, target, and request digest before adding, changing, revoking, binding, or unbinding sensitive provider credentials or SF accounts. Operators and platform administrators SHALL NOT mutate tenant provider configuration.

#### Scenario: Verified payload is changed before submit
- **GIVEN** an Admin completed an OTP for one masked SF-account binding request
- **WHEN** the client changes the target warehouse, account input, or credential revision and reuses that challenge
- **THEN** the final action-digest check rejects the request
- **AND** no secret pointer, claim, or warehouse binding changes

### Requirement: SF monthly accounts have one global current claim
The system MUST normalize an SF monthly-account input only with provider-approved rules that preserve leading zeroes, derive a purpose-separated keyed fingerprint, and maintain exactly one permanent global claim row for that fingerprint. Across all warehouses and tenants, only one owner triple may be `reserved` or `active`; conflicts SHALL return the non-disclosing `SF_ACCOUNT_UNAVAILABLE` result.

#### Scenario: Two tenants bind the same account concurrently
- **GIVEN** two Admins submit equivalent normalized account values for different warehouses
- **WHEN** their claim transactions race
- **THEN** at most one claim generation reaches active ownership
- **AND** the loser learns neither the tenant nor warehouse holding the claim
- **AND** neither secret plaintext nor a reversible account value is stored in the claim table

### Requirement: SF claim release is explicit and historical facts survive
The system MUST allow only an active Admin of the currently bound warehouse's tenant to release an SF claim through the D48 action, except for the fenced system-deletion workflow after its confirmed tombstone acknowledgement. Normal release SHALL clear current ownership and advance the append-only claim event chain without deleting provider-account identities, credential revisions, or shipment snapshots; expired and suspended tenants receive no unbind exception.

#### Scenario: Original tenant releases and a new tenant rebinds
- **GIVEN** the original Admin successfully unbinds an account
- **WHEN** another tenant later submits and verifies the same normalized account
- **THEN** the permanent claim advances through a higher reserved and active generation for the new owner
- **AND** old shipments still resolve their original account, binding, warehouse, and credential revision snapshots

### Requirement: New SF operations resolve one consistent warehouse context
The system MUST resolve official estimates, new waybill orders, and current print prerequisites from the main device's current warehouse and require that the work-queue warehouse, device warehouse, SF binding, global claim owner, account revision, API connection revision, and sender details all agree. Missing or inconsistent facts SHALL fail closed without falling back to process environment variables, a default warehouse, another account, or another tenant.

#### Scenario: Work queue and device warehouse disagree
- **GIVEN** an order appears in warehouse A's queue but its device now belongs to warehouse B
- **WHEN** an SF action is attempted
- **THEN** the resolver denies the action before contacting SF
- **AND** it does not borrow warehouse A's account or warehouse B's details selectively

### Requirement: Shipments freeze exact provider context
The system MUST snapshot the warehouse UUID, account and binding revisions, masked account hint, sender details, integration and account credential revision UUIDs, product type, and provider operation identity when a waybill is created. Historical query, cancellation, and reconciliation SHALL use those exact revisions even after current pointers, defaults, bindings, or root-key envelopes change.

#### Scenario: Credentials rotate after shipment creation
- **GIVEN** a shipment was created with credential revision 4 and current revision is later 5
- **WHEN** the system queries or cancels the historical shipment
- **THEN** it resolves revision 4 through its authorized historical path
- **AND** it never retries with revision 5 merely because the old call failed

### Requirement: Device movement after waybill requires cancel and rebuild
The system MUST block printing and actual shipment when a device moved after waybill creation. The old waybill SHALL be explicitly cancelled using its saved context; only confirmed provider cancellation, or completed review of an unknown result, may authorize a new waybill and two-sheet context for the new warehouse.

#### Scenario: Cancellation response is lost
- **GIVEN** the cancellation request may have reached SF but its response was lost
- **WHEN** the user tries to rebuild immediately
- **THEN** the old operation remains in an unknown/review state
- **AND** no replacement waybill or print submission occurs until reconciliation establishes a safe result

### Requirement: A warehouse without SF remains usable outside SF actions
The system MUST allow inventory, accessory, customer, and rental management for a ready warehouse without an active SF account. It SHALL require explicit manual logistics confirmation when official estimation is unavailable and SHALL block only operations that require a new SF side effect or first sheet, with role-appropriate guidance to the warehouse's configuration page.

#### Scenario: Operator ships from an unbound warehouse
- **GIVEN** a rental's device is in a ready warehouse with no SF binding
- **WHEN** an Operator tries to create a waybill
- **THEN** the system reports the missing warehouse binding as a configuration prerequisite
- **AND** no provider call or fallback-account call is made
- **AND** the Operator receives guidance to contact an Admin

### Requirement: Xianyu synchronization is tenant-scoped durable work
The system MUST schedule one deduplicated Xianyu reconciliation job per eligible tenant every three minutes, using that tenant's current connection revision and writing only its tenant database. A user refresh SHALL enqueue a higher-priority tenant job deduplicated within the approved 180-second window; pages SHALL read the local summary and last-success time rather than calling Xianyu per account or tab.

#### Scenario: Multiple tabs request refresh
- **GIVEN** several sessions in one tenant request Xianyu refresh within 180 seconds
- **WHEN** the requests are accepted
- **THEN** they reference one durable tenant-scoped job
- **AND** no browser directly calls Xianyu
- **AND** another tenant's schedule, credentials, or summary is unaffected

### Requirement: Platform SMS uses one production identity
The system MUST send registration, login, and sensitive-action OTPs through the platform's Tencent Cloud account, approved corporate signature, and approved templates; tenant branding SHALL NOT alter that signature. Production SHALL fail closed when qualification, signature, template, carrier filing, or controlled real-number verification is incomplete, while a fake provider is permitted only in explicitly non-production environments.

#### Scenario: Tenant changes display name
- **GIVEN** a tenant Admin changes tenant branding
- **WHEN** the next legitimate OTP is sent
- **THEN** the approved platform signature and template remain unchanged
- **AND** neither the code nor Tencent secret appears in the API response, database plaintext, logs, or metrics

