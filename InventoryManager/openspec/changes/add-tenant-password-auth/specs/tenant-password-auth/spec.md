## ADDED Requirements

### Requirement: Explicit tenant authentication mode
The application MUST accept only `sms` or `password` as `TENANT_AUTH_MODE` and MUST default to `sms`. Production SMS mode MUST require complete Tencent SMS configuration and a real Tencent sender, while production password mode MUST start without Tencent credentials and MUST NOT initialize an SMS sender. Worker startup MUST NOT require an authentication sender in either mode.

#### Scenario: Existing production SMS deployment starts
- **WHEN** production starts with `TENANT_AUTH_MODE=sms`, complete Tencent SMS configuration, and no custom sender
- **THEN** the application uses the Tencent sender and preserves the existing SMS login behavior

#### Scenario: Password-only production deployment starts
- **WHEN** production starts with `TENANT_AUTH_MODE=password` and no Tencent SMS credentials
- **THEN** the application starts without constructing an SMS sender

#### Scenario: Invalid authentication mode fails startup
- **WHEN** app or worker startup receives a tenant authentication mode other than `sms` or `password`
- **THEN** startup fails with a configuration error

### Requirement: Fail-closed method discovery and routing
The system MUST expose a public authentication configuration response containing only the selected method. An authentication endpoint for a non-selected method MUST fail closed with the stable code `AUTH_METHOD_DISABLED` and MUST perform no credential or sender work.

#### Scenario: Public client discovers password mode
- **WHEN** an unauthenticated client requests the authentication configuration in password mode
- **THEN** the response data contains only `method: password`

#### Scenario: SMS is disabled in password mode
- **WHEN** a client calls either SMS endpoint while password mode is selected
- **THEN** the endpoint returns `AUTH_METHOD_DISABLED` without sending or verifying a code

#### Scenario: Password login is disabled in SMS mode
- **WHEN** a client calls password login while SMS mode is selected
- **THEN** the endpoint returns `AUTH_METHOD_DISABLED` without checking a member password

### Requirement: Password credential storage and policy
Tenant member passwords MUST be stored only as Werkzeug password hashes. The system MUST accept passwords from 12 through 128 characters and MUST persist failed-attempt count, lock expiry, and password-change time in the control database through a new reversible migration.

#### Scenario: Valid password is stored
- **WHEN** an authorized CLI or password-change request sets a 12 to 128 character password
- **THEN** only its salted hash and non-secret state are persisted

#### Scenario: Invalid password is rejected
- **WHEN** a password is shorter than 12 or longer than 128 characters
- **THEN** the system returns a safe policy error without changing credentials or sessions

### Requirement: Tenant password login and brute-force protection
Password login MUST accept normalized mainland-China phone plus password, MUST use the existing tenant session and login payload shape, and MUST return the same generic authentication failure for unknown, disabled, passwordless, wrong-password, locked, and advisory-lock-timeout identities. Each syntactically valid normalized phone MUST acquire the same bounded, hashed-name MariaDB advisory lock before member lookup and Werkzeug verification so concurrent existing and unknown candidates serialize equivalently. Invalid phones MUST still perform dummy Werkzeug verification. Five consecutive failed password attempts MUST lock the member for fifteen minutes; a successful login MUST reset failure state. Login MUST NOT bypass existing member, tenant, provisioning, expiry, or business access semantics.

#### Scenario: Active member signs in successfully
- **WHEN** an active password-enabled member submits the correct phone and password while not locked
- **THEN** the system creates the existing tenant session cookie, resets failed-attempt state, and returns the member, tenant access status, and CSRF token

#### Scenario: Fifth failure locks the identity
- **WHEN** an eligible member submits an incorrect password five times
- **THEN** the fifth request returns the generic failure and persists a lock expiring fifteen minutes later

#### Scenario: Locked and nonexistent identities are indistinguishable
- **WHEN** a locked member or an unknown phone attempts login
- **THEN** both receive the same status, code, and generic message

#### Scenario: Concurrent candidate checks serialize without identity leakage
- **WHEN** concurrent requests submit the same normalized phone, whether it belongs to a member or not
- **THEN** they serialize through the same hashed-name advisory lock and any lock timeout returns the generic authentication failure

#### Scenario: Restricted tenant receives no business access
- **WHEN** a member authenticates correctly but their tenant is suspended, expired, or not provisioned
- **THEN** the login payload reports the existing restricted access status and protected business routes remain unavailable

### Requirement: Authenticated tenant password change
An admin or operator with a valid tenant cookie MUST be able to change their own password by providing the current and new passwords with a matching CSRF token. Success MUST update the hash and change timestamp, reset lock state, revoke every other tenant session for that member, and keep the current session and CSRF token valid.

#### Scenario: Member changes password
- **WHEN** an authenticated member provides a correct current password, a policy-compliant new password, and valid CSRF
- **THEN** the password changes, other tenant sessions are revoked, and the current session can continue making CSRF-protected requests

#### Scenario: Current password is wrong
- **WHEN** an authenticated member provides an incorrect current password
- **THEN** the system returns a generic current-password failure and changes neither the credential nor sessions

#### Scenario: CSRF is absent or invalid
- **WHEN** an authenticated password-change request omits or supplies a stale CSRF token
- **THEN** the request fails with `CSRF_INVALID` and changes neither the credential nor sessions

### Requirement: Secret-safe initial password command
The application MUST register a CLI that selects a tenant member by normalized phone and reads a new password only from standard input or a hidden interactive prompt. The command MUST reject unknown members and invalid passwords clearly, MUST never accept or output plaintext passwords, and MUST revoke all existing tenant sessions for the selected member after success.

#### Scenario: Automation pipes an initial password
- **WHEN** an operator runs the command with `--phone` and `--password-stdin` through a non-TTY container execution
- **THEN** the command reads one password from stdin, stores only its hash, revokes existing sessions, and emits only a non-secret success message

#### Scenario: Command targets an unknown member
- **WHEN** the normalized phone does not identify a tenant member
- **THEN** the command fails clearly without creating credentials or echoing input

#### Scenario: Hidden prompt has no terminal
- **WHEN** the command omits `--password-stdin` while standard input is not a real TTY
- **THEN** it fails before reading input and instructs the operator to use `--password-stdin` without emitting a fallback warning or secret

### Requirement: Mode-aware tenant user interface
The desktop frontend MUST load the public authentication configuration before rendering tenant login, MUST preserve the existing SMS UI in SMS mode, and MUST render phone/password login in password mode. The authenticated shell MUST provide both admins and operators a password-change page and MUST preserve the active CSRF header after a successful change.

#### Scenario: Password-mode login renders
- **WHEN** the public configuration selects password mode
- **THEN** the login page shows phone and password fields and does not show SMS code controls

#### Scenario: Authentication configuration cannot be loaded
- **WHEN** the public configuration request fails
- **THEN** the login page renders no SMS or password form and provides an explicit retry state

#### Scenario: Operator opens password change
- **WHEN** an authenticated operator uses the AppHeader password-change link
- **THEN** the router allows the operator to open the authenticated password-change page

#### Scenario: Password change preserves CSRF
- **WHEN** the frontend completes a password change successfully
- **THEN** the auth store retains its current tenant session CSRF token and default CSRF request header
