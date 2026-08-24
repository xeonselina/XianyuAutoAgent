## ADDED Requirements

### Requirement: Versioned Core entitlement contract
The system MUST evaluate subscription access from an immutable plan revision and entitlement snapshot. SaaS Core SHALL expose one supported entitlement schema whose only commercial hard quota is `member_seats = 10`, counted as active memberships plus unexpired pending invitations; device count, rental count, ordinary API volume, integration count, and signed-in device count MUST NOT be treated as plan quotas.

#### Scenario: Concurrent requests cannot occupy an eleventh seat
- **GIVEN** a tenant has nine active memberships and one unexpired pending invitation
- **WHEN** two Admin requests concurrently try to create or accept another invitation
- **THEN** the final control-database transactions serialize the seat calculation
- **AND** neither transaction can make the committed occupied-seat count exceed ten
- **AND** a rejected request reports a seat-limit result without consuming an invitation or changing another tenant

#### Scenario: Capacity protection is not reported as a plan quota
- **GIVEN** a tenant is within its ten-seat entitlement
- **WHEN** a request is rejected by rate, payload, connection, or provider capacity protection
- **THEN** the response does not claim that a device, rental, API, or integration quota is exhausted

### Requirement: Invitation seat lifecycle
The system MUST give every pending invitation a seven-day default expiry and reserve exactly one seat in the issuing tenant. Revocation, expiry, link rotation, or supersession after the canonical phone establishes a membership in another tenant SHALL release the corresponding reservation atomically, while accepting an invitation SHALL convert its reservation to an active membership without briefly counting two seats.

#### Scenario: First tenant membership wins across parallel invitations
- **GIVEN** the same canonical phone has valid pending invitations from multiple tenants and no existing membership
- **WHEN** invitation acceptance and redemption-code registration race
- **THEN** at most one transaction establishes a membership for that phone
- **AND** the winning transaction supersedes all other pending invitations and releases their seats in the same control-database transaction
- **AND** old links and OTPs cannot establish a second membership or disclose the winning tenant

### Requirement: Redemption codes are single-use immutable entitlements
The system MUST generate each redemption code from a CSPRNG as a 26-character Crockford Base32 bearer secret, normalize every input through the one approved canonicalization function, and enforce a unique SHA-256 lookup hash. The code record SHALL freeze its plan revision, entitlement snapshot, exact service duration, redemption deadline, and recovery-run provenance; one code can commit exactly one registration or renewal.

#### Scenario: Concurrent redemption has one winner
- **GIVEN** an active unexpired code created under the current completed recovery run
- **WHEN** registration and renewal requests try to consume the same normalized code concurrently with different idempotency keys
- **THEN** row locking or an atomic conditional update allows at most one committed redemption
- **AND** the losing request does not change a membership, subscription, code binding, or expiry

#### Scenario: Input variants resolve to the same code
- **GIVEN** a bearer code containing display hyphens or permitted `O`/`I`/`L` aliases
- **WHEN** the code is submitted through preview, registration, renewal, import, or platform reveal paths
- **THEN** every path applies NFKC normalization, removes Unicode whitespace and ASCII hyphens, uppercases ASCII, maps the approved aliases, and requires exactly 26 valid characters
- **AND** all variants resolve to the same lookup hash

### Requirement: Redemption-code plaintext is narrowly controlled
The system MUST encrypt retrievable code plaintext with a purpose- and record-derived AES-256-GCM key from the versioned platform root key, while list APIs return only masked values. Platform generation SHALL allow a one-time CSV response; historical batches MUST NOT be bulk-exported again, and every authorized single-code reveal, generation, export, revocation, replacement, or denial SHALL be audited without logging plaintext.

#### Scenario: Historical batch cannot be exported again
- **GIVEN** a platform administrator already received the successful generation response for a batch
- **WHEN** the administrator later opens that batch
- **THEN** the UI and API do not offer another full-batch plaintext export
- **AND** an administrator with reveal permission may reveal individual codes with a separate audit event for each reveal

### Requirement: Recovery state gates code operations
The system MUST fail closed for code generation, preview, reservation, registration, and renewal unless the current host-recovery run is `completed`. Codes recovered as `active` or `reserved` SHALL transition irreversibly to `recovery_revoked`, and newly issued codes SHALL be bound to the then-current completed run.

#### Scenario: Restored code cannot be redeemed
- **GIVEN** a host restore has created a new recovery run and an old snapshot contains an active or reserved code
- **WHEN** a client previews or redeems that code before or after tenant review
- **THEN** the code remains non-redeemable in `recovery_revoked`
- **AND** only the confirmed replacement-code workflow may issue one new successor after the run is completed

### Requirement: Registration is a fenced provisioning state machine
The system MUST implement registration as a resumable state machine rather than a cross-database pseudo-transaction. It SHALL consume a valid action-purpose `register` OTP for the canonical `+86` phone, reserve one eligible code to an immutable user and registration attempt, provision and smoke-test a database addressed by immutable tenant/database UUIDs, and publish the route, first Admin membership, subscription event, released hold baseline, public name claim, and redeemed code only through one fenced final control-database transaction.

#### Scenario: Successful registration publishes all control-plane anchors together
- **GIVEN** the current recovery run is completed, the code is active, the user has no membership, and the provisional tenant database has the expected `database_identity` and schema digest
- **WHEN** the current worker reaches final commit with a valid generation and lease
- **THEN** one control-database transaction creates the immutable registration commit, Admin membership, subscription and event, route anchor, public name claim, initial released hold, and redeemed-code references
- **AND** pending invitations for the phone are superseded and their seats released in that transaction
- **AND** no business route is published before those facts agree

#### Scenario: A stale worker cannot publish
- **GIVEN** the provisioning generation, recovery run, user state, replacement lineage, code binding, or database identity changed after work began
- **WHEN** a stale worker attempts final commit
- **THEN** the current-read fence rejects it before any membership, subscription, code, name, or route is published

### Requirement: Failed registration has only the confirmed recovery paths
The system MUST keep a failed registration code reserved to its original user and attempt. Only that user, after a fresh `register` OTP for the same canonical phone, may retry the same attempt; the platform SHALL expose no retry, abandon, or cleanup action and may only issue the unique confirmed replacement code by atomically fencing the source attempt and worker, permanently revoking the old code as replaced, and copying its immutable entitlement terms into a new random bearer code with a newly selected future redemption deadline.

#### Scenario: Original user retries a failed attempt
- **GIVEN** provisioning failed and the code remains reserved to an attempt
- **WHEN** the original user proves the same canonical phone with a fresh registration OTP
- **THEN** the system may advance the attempt generation and retry idempotently
- **AND** it does not create a second attempt, change the requested entitlement, or release the old code to another user

#### Scenario: Replacement wins against final commit
- **GIVEN** an eligible failed attempt and source code have no completed registration commit or prior successor
- **WHEN** an authorized platform replacement request linearizes first
- **THEN** one control transaction fences the attempt and worker, records `superseded_by_replacement`, permanently revokes the old code, and creates exactly one successor with new UUID and cryptographic context
- **AND** every late final commit fails before publishing tenant control-plane facts
- **AND** a system-only janitor handles any real provisional resources without blocking or revoking the successor

### Requirement: Admin renewal extends the exact consumed entitlement
The system MUST allow only an authenticated active Admin membership to redeem a code for an existing tenant in effective `active` or `expired` state. The final transaction SHALL re-lock and current-read the tenant, recovery run, hold, deletion, suspension, code, membership, access version, and subscription, then calculate `max(current_expires_at, database_current_time) + code.duration` and append an immutable subscription event using the consumed code's frozen terms.

#### Scenario: Expired Admin renews from the current time
- **GIVEN** the tenant is expired but otherwise released and an Admin has reached the expired page
- **WHEN** the Admin redeems a valid current-run code
- **THEN** the new expiry equals database current time plus the code's exact duration
- **AND** the same transaction consumes the code, updates the subscription, and records before/after terms

#### Scenario: Suspension starts after preliminary validation
- **GIVEN** a renewal request passed an earlier UI or middleware check
- **WHEN** the tenant becomes suspended before the final redemption transaction
- **THEN** final current-read validation rejects the renewal
- **AND** the code and subscription remain unchanged

### Requirement: Expired access is one closed renewal loop
The system MUST let all valid members authenticate when a tenant is expired but route them to the same expired-service page. Operators SHALL only view that page and log out; Admins SHALL additionally submit redemption-code renewal, while account security, member settings, provider configuration or unbinding, and all business APIs remain denied.

#### Scenario: Expired Operator cannot enter business routes
- **GIVEN** an Operator has a valid phone OTP and membership in an expired tenant
- **WHEN** the Operator signs in or calls a business API directly
- **THEN** the UI routes to the expired page and the API denies the business request
- **AND** only page viewing and logout remain available

### Requirement: Platform service-period adjustment is a fresh-factor action
The system MUST let any active platform administrator adjust an `active`, `expired`, or fully suspended tenant by adding or subtracting positive integer days, or by selecting a distinct expire-now action. Each new adjustment SHALL require a fresh TOTP verification or one unused recovery code and SHALL atomically consume the factor evidence, current-read the expected subscription revision and database time, append an immutable event, update expiry, and write platform audit; it MUST NOT accept an arbitrary target timestamp, remove suspension, or create payment/refund financial state.

#### Scenario: Suspended tenant receives a days adjustment without resuming
- **GIVEN** suspension is complete and no recovery hold or deletion transition is active
- **WHEN** a platform administrator proves a fresh factor and adds days
- **THEN** the service expiry changes from a database-time calculation
- **AND** the tenant remains suspended
- **AND** the event records a bounded reason, safe note, and optional offline reference but no amount, currency, payment status, or refund assertion

#### Scenario: Factor cannot be reused for another adjustment
- **GIVEN** a TOTP time step or recovery code was consumed by a successful adjustment
- **WHEN** the administrator submits a different adjustment with that evidence
- **THEN** the request is rejected without changing subscription state

