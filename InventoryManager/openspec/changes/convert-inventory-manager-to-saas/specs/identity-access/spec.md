## ADDED Requirements

### Requirement: Normalize all tenant identities to supported mainland-China mobile numbers

The tenant identity system MUST use one versioned server-side phone normalizer for registration, login, invitations, invitation acceptance, phone change, deletion verification, and other tenant SMS challenges, and Core SHALL create tenant identities only for valid mainland-China `+86` mobile numbers stored as canonical ASCII E.164.

#### Scenario: Equivalent supported input is submitted
- **WHEN** a user enters `1xxxxxxxxxx` or an explicitly `+86` equivalent containing only allowed ASCII spaces or hyphens
- **THEN** the server SHALL normalize it before account lookup, rate limiting, HMAC context construction, or provider dispatch and use one canonical `+861xxxxxxxxxx` identity

#### Scenario: An unsupported or ambiguous number is submitted
- **WHEN** input uses another country or region, `0086`, an unsigned `86` prefix, Unicode digits, letters, parentheses, an extension, or is not a valid CN mobile number
- **THEN** the system SHALL reject it before creating a user, challenge, invitation seat, or SMS delivery attempt

#### Scenario: A business contact number is stored
- **WHEN** a customer, warehouse, sender, receiver, or logistics telephone is processed
- **THEN** the system SHALL apply that business field's provider rules rather than treating D46's tenant-login restriction as its identity validator

### Requirement: Issue and consume purpose-bound SMS challenges securely

The system MUST use the platform Tencent Cloud SMS account and fixed platform signature for six-digit tenant verification challenges, store only a root-key-derived purpose-specific HMAC plus bounded metadata, and SHALL consume a challenge at most once for its exact user, canonical phone, tenant/session context, purpose, action payload, and current revision.

#### Scenario: A verification challenge is sent
- **WHEN** a valid request passes normalization and application rate limits
- **THEN** the system SHALL create a five-minute challenge, enforce a 60-second resend cooldown, permit no more than five wrong attempts, and record delivery without storing or logging the plaintext code

#### Scenario: An actor attempts to reuse a code
- **WHEN** a code issued for login, registration, invitation acceptance, a D48 action, phone change, or deletion is supplied for a different purpose, payload, session, tenant, or revision
- **THEN** the system SHALL reject it and SHALL NOT treat an earlier verification time as authorization

#### Scenario: Provider delivery is uncertain
- **WHEN** Tencent Cloud times out after a challenge was committed
- **THEN** the challenge SHALL enter `send_unknown` and reuse that bounded attempt for controlled verification handling rather than generating unlimited new codes

### Requirement: Enforce SMS abuse controls in the control database

The system MUST atomically enforce versioned SMS limits across purpose values: at most five sends per canonical phone per rolling hour, ten per canonical phone per Asia/Shanghai calendar day, thirty per trusted source IP per rolling hour, and two hundred per trusted source IP per Asia/Shanghai calendar day; Tencent Cloud console controls SHALL be aligned as a second layer.

#### Scenario: A caller switches verification purposes
- **WHEN** one canonical phone has already consumed its cross-purpose hourly or daily allowance
- **THEN** requests under another purpose SHALL remain rate limited and return a stable retry indication without revealing whether an account exists

#### Scenario: A client forges forwarding headers
- **WHEN** the request supplies its own `X-Forwarded-For` outside the configured trusted proxy boundary
- **THEN** the application SHALL discard that value and count only the source reconstructed by the trusted proxy or a conservative unknown-source bucket

### Requirement: Use revocable MySQL-backed browser sessions

Tenant authentication MUST use control-database server-side sessions and a host-only cookie containing only an opaque CSPRNG bearer token of at least 256 bits; the database SHALL store only its SHA-256 digest and enforce idle expiry, absolute expiry, user auth version, tenant access version, membership, role, and effective tenant gate on every request.

#### Scenario: OTP login succeeds
- **WHEN** the login challenge is atomically consumed for an eligible user and membership
- **THEN** the system SHALL create a fresh session row, rotate away any pre-login or replaced token, and issue a `Secure`, `HttpOnly`, `SameSite=Lax` cookie over HTTPS

#### Scenario: A copied or stale cookie is presented
- **WHEN** its database row is absent, revoked, expired, or its user/tenant auth version no longer matches
- **THEN** the request SHALL be unauthenticated without falling back to a signed stateless cookie, process cache, JWT, or client-carried identity

#### Scenario: Session state is exposed to a client surface
- **WHEN** a response, URL, HTML document, log, audit event, metric, browser storage, or service-worker cache is produced
- **THEN** it SHALL NOT contain the raw bearer token or its database digest

### Requirement: Protect session and state-changing operations against cross-site requests

All tenant and platform state-changing browser requests MUST require a CSRF token and an explicit production CORS allowlist; CSRF material SHALL be distinct from the session bearer token and session revocation endpoints SHALL use non-GET methods.

#### Scenario: A state-changing request lacks valid CSRF proof
- **WHEN** an authenticated browser attempts a member, session, subscription, integration, or other mutation without the current independent CSRF token
- **THEN** the system SHALL reject the request without consuming an OTP or committing a state change

### Requirement: Provide per-device session visibility and immediate revocation

An authenticated tenant user MUST be able to list and revoke only their own browser-session devices, revoke the current or a specified device by an unguessable session UUID, and revoke all devices; member removal, phone change, and security resets SHALL invalidate the affected sessions transactionally.

#### Scenario: A user revokes one device
- **WHEN** the supplied session UUID belongs to that same user
- **THEN** the control-plane transaction SHALL set its revocation time and reason before the client clears its cookie, without incrementing the user's global auth version

#### Scenario: A user revokes all devices
- **WHEN** the all-devices action passes CSRF and authorization checks
- **THEN** the transaction SHALL increment `users.auth_version` and revoke every active session including the current device

#### Scenario: A user targets another member's session
- **WHEN** the session UUID, token digest, or tenant input does not identify a session owned by the authenticated user
- **THEN** the system SHALL reject the request without revealing whether that session exists

### Requirement: Enforce two fixed tenant roles through backend capabilities

SaaS Core MUST expose only Admin and Operator tenant roles, evaluate authorization by backend capability rather than scattered UI role checks, preserve at least one active Admin, and SHALL NOT permit a tenant membership to become a platform administrator.

#### Scenario: An Operator performs daily business work
- **WHEN** the Operator creates or edits inventory, rentals, shipments, printing, inspection, relay, or warehouse movements
- **THEN** the backend SHALL authorize the applicable business capability while denying member, subscription, and third-party credential administration

#### Scenario: An Admin manages tenant configuration
- **WHEN** an active Admin accesses members, integrations, tenant branding, or redemption-code renewal in an otherwise eligible tenant state
- **THEN** the backend SHALL enforce the corresponding capability and any additional action-specific confirmation

#### Scenario: The last active Admin would be removed
- **WHEN** a downgrade, disable, removal, or concurrent member change would leave zero active Admin memberships
- **THEN** the final transaction SHALL fail even if a valid high-risk OTP was supplied or an Admin invitation is still pending

### Requirement: Hand off membership through single-use invitations

An active tenant Admin MUST be able to create or regenerate one pending invitation per tenant and canonical phone for an immutable Admin or Operator role, with a seven-day expiry and at least 192 bits of random token entropy; Core SHALL return the link once for the Admin to send out-of-band and SHALL NOT send invitation notifications by SMS.

#### Scenario: An Admin creates an Operator invitation
- **WHEN** the phone is a supported canonical `+86` identity with no unreleased membership and the tenant's active-member plus unexpired-pending count remains at or below ten
- **THEN** the system SHALL create or reuse an unprivileged coordinating user, reserve exactly one seat, store only the token digest, and return a single-use fragment link

#### Scenario: An Admin regenerates an existing invitation
- **WHEN** the same tenant and phone already have a pending invitation
- **THEN** the system SHALL invalidate the old token, issue a new token and seven-day window, keep one seat reservation, and write an audit event

#### Scenario: The invitation link is merely opened
- **WHEN** a bearer presents the current token without the bound phone's `accept_invitation` OTP
- **THEN** the system SHALL return only a minimal masked invitation summary and SHALL NOT create membership or permissions

### Requirement: Linearize invitation acceptance across tenants

Invitation acceptance MUST atomically bind the current token generation to an `accept_invitation` challenge for the exact canonical phone, create at most one active tenant membership for that phone, accept the winning invitation, and irreversibly supersede and release all other tenants' pending invitations for that phone.

#### Scenario: One phone has pending invitations from two tenants
- **WHEN** the phone owner successfully accepts one invitation
- **THEN** the same transaction SHALL verify the winning tenant join gate and seat guard, consume the OTP, establish the immutable-role membership, clear coordinating references from all terminal invitations, and release the losing seat reservations

#### Scenario: Two acceptances race
- **WHEN** two tenants concurrently try to accept invitations for the same canonical phone
- **THEN** at most one transaction SHALL establish membership and the loser SHALL observe the committed ownership without reviving its invitation

#### Scenario: A losing tenant is suspended or expired
- **WHEN** another tenant wins acceptance for the shared phone
- **THEN** the transaction SHALL still be allowed to monotonically supersede the losing invitation and release its seat but SHALL NOT add any permission, job, or resource to the losing tenant

### Requirement: Require action-bound OTP for tenant Admin high-risk changes

The system MUST require a fresh D48 SMS challenge bound to the current Admin, browser session, tenant, action subtype, target revision, and canonical payload for integration credential changes, SF account bind/unbind/rebind, Admin invitations or effective Admin permission changes, and tenant deletion request or cancellation; successful verification SHALL NOT authorize any other action.

#### Scenario: A high-risk action is confirmed
- **WHEN** the same browser session resubmits the identical normalized payload with a valid action-bound challenge and all current capability, tenant-gate, target-revision, CSRF, seat, and last-Admin checks still pass
- **THEN** the final transaction SHALL consume the challenge once and atomically commit the mutation plus its security event or authorized outbox

#### Scenario: The payload or target changed after challenge issuance
- **WHEN** any bound field, current revision, session, tenant gate, or actor differs at confirmation time
- **THEN** the action SHALL fail without treating the challenge as a reusable recent-verification window

#### Scenario: An ordinary Operator member action is performed
- **WHEN** an Admin invites, enables, disables, or removes only an Operator and no effective Admin permission changes
- **THEN** normal capability, CSRF, seat, and tenant checks SHALL apply without adding a D48 OTP

### Requirement: Change tenant identity phones only with two bound OTPs

An Admin or Operator MUST change their own canonical phone only by consuming `phone_change_old` and `phone_change_new` challenges bound to one change request and browser session in the same final transaction; the system SHALL preserve the immutable user UUID, revoke all old sessions, and require login with the new phone.

#### Scenario: Both old and new numbers are verified
- **WHEN** the old challenge targets the authenticated user's current phone, the new challenge targets the request's supported unclaimed `+86` phone, and all identity uniqueness checks still pass
- **THEN** the transaction SHALL consume both codes in their fixed roles, update the canonical phone and verification time, increment auth version, and revoke every prior session

#### Scenario: The old phone cannot receive an OTP
- **WHEN** the user cannot complete `phone_change_old`
- **THEN** Core SHALL return `PHONE_CHANGE_OLD_VERIFICATION_REQUIRED` and SHALL NOT offer a platform override, alternate recipient, document review, support ticket, CLI phone edit, identity merge, or impersonation path

#### Scenario: Another active Admin can help a member who lost their phone
- **WHEN** the tenant has another active Admin and the lost-phone membership can be removed without violating the last-Admin invariant
- **THEN** that Admin MAY use the ordinary removal flow and create a separate new-phone invitation, producing a new user and membership without rewriting or merging the old identity history

#### Scenario: The lost-phone user is the last active Admin
- **WHEN** no other active Admin membership exists
- **THEN** Core SHALL fail closed until the old phone is recovered outside the system and the normal dual-code flow can be completed

### Requirement: Keep platform administrator identity independent

Platform administrators MUST use a separate global identity domain, password, confirmed TOTP, one-time recovery codes, server-side sessions, Cookie, CSRF boundary, and audit trail; they SHALL NOT register publicly, authenticate with tenant SMS, hold tenant membership, downgrade into tenant login, or impersonate a tenant user.

#### Scenario: The first platform administrator is bootstrapped
- **WHEN** an authorized operator invokes the audited host CLI
- **THEN** the CLI SHALL create a short-lived one-time setup challenge and a `setup_pending` account that receives no platform capability until a formal password and TOTP are configured and recovery codes are shown once

#### Scenario: A platform administrator logs in
- **WHEN** the correct password and a current non-replayed TOTP or unused current-generation recovery code are verified
- **THEN** the system SHALL issue a fresh `/platform`-scoped host-only server session distinct from every tenant session

#### Scenario: TOTP or recovery material is reset
- **WHEN** the credential is replaced, regenerated, or reset after a security event
- **THEN** the system SHALL advance the relevant generation or auth version, revoke superseded factors and affected platform sessions, preserve at least one fully active platform administrator, and record an immutable audit event

### Requirement: Restrict platform tenant access to audited read-only views

An authenticated platform administrator MUST select one trusted tenant at a time and use that tenant's independent SELECT-only route for business support reads; the platform SHALL deny tenant business writes, provider calls, printing, file generation, impersonation, Secret plaintext access, unbounded cross-tenant search, and cross-tenant bulk business export.

#### Scenario: A platform administrator lists tenant business records
- **WHEN** the target tenant is in a state that permits platform diagnosis and its read route identity is valid
- **THEN** the platform SHALL return a paginated, minimized DTO with PII masked by default and `Cache-Control: private, no-store`

#### Scenario: Full PII is explicitly viewed
- **WHEN** a dedicated read capability and reason allow the detail value to be returned
- **THEN** the system SHALL append an audit event containing actor, tenant, technical resource, reason, and request ID before serializing the response

#### Scenario: Platform read auditing fails
- **WHEN** the final audit event for a successful, failed, or denied read cannot be committed
- **THEN** the system SHALL fail closed and SHALL NOT return tenant business data

### Requirement: Apply tenant state gates before role and data authorization

Every tenant request MUST evaluate recovery hold, deletion, suspension, subscription, access version, and setup gates before resolving business capabilities or opening the tenant database, and restricted sessions SHALL expose only the explicitly approved state-specific surface.

#### Scenario: A subscription is expired
- **WHEN** an Admin or Operator completes valid SMS login
- **THEN** both SHALL reach the same expiration page; Operator SHALL only see minimal subscription state and logout, while Admin MAY additionally submit an existing redemption code
- **AND** neither role SHALL access account security, members, integrations, SF binding or unbinding, tenant settings, or business APIs until renewal returns the tenant to active

#### Scenario: A tenant is suspended
- **WHEN** a user signs in after the suspension barrier
- **THEN** Operator SHALL only see the suspension notice and logout, while Admin MAY additionally use only their own approved account-security actions
- **AND** no role SHALL access renewal, members, integrations, SF unbinding, or business APIs until a separate platform resume completes and the user logs in again

#### Scenario: A tenant is under a recovery hold
- **WHEN** the current run or tenant hold is missing, mismatched, or not released
- **THEN** normal tenant session issuance and tenant database routing SHALL fail closed with a non-PII recovery-in-progress response

### Requirement: Exclude tenant API keys from SaaS Core

SaaS Core MUST authenticate tenant business APIs only with current MySQL-backed user sessions, membership, and RBAC, and SHALL NOT provide tenant API keys, machine identities, external tenant authentication headers, key lifecycle tables, Secret reveal, rotation, scope, recovery, or management endpoints.

#### Scenario: The legacy external API key route is requested
- **WHEN** a caller presents the prior global `X-API-Key` or attempts to use `/external-api` as a tenant authentication path
- **THEN** the Core deployment SHALL remove the route or keep it unreachable and SHALL NOT translate the credential into tenant context

### Requirement: Eliminate generic application signing secrets

SaaS Core MUST NOT load, require, restore, or authorize with the legacy Flask `SECRET_KEY` or global `API_KEY`. Browser authentication SHALL use revocable MySQL-backed opaque sessions and independent per-session CSRF material rather than signed identity cookies. Any retained stateless workflow proof MUST use a versioned, purpose-separated key derived from the repository-external platform root key, MUST bind the trusted tenant, actor session, canonical action, authoritative revisions, and expiry, and MUST NOT use the root key directly or share a derivation domain with another workflow.

#### Scenario: Legacy application keys remain after upgrade
- **GIVEN** an old environment file, snapshot, or restored configuration still contains `SECRET_KEY` or `API_KEY`
- **WHEN** a caller presents an old signed artifact, API-key header, or Cookie that depended on either value
- **THEN** no tenant or platform identity is established and no business read, write, or workflow authorization occurs
- **AND** normal Core startup and authenticated sessions do not require either legacy value

#### Scenario: A Gantt reorder preview is executed
- **GIVEN** an authenticated tenant member obtains a short-lived reorder preview proof
- **WHEN** the member submits the proof for execution
- **THEN** the server verifies a Gantt-specific platform-root-derived HMAC bound to the current tenant, actor session, canonical payload, authoritative revisions, snapshot, and expiry
- **AND** a cross-tenant, cross-session, stale, tampered, or legacy-`SECRET_KEY` proof is rejected before any mutation
