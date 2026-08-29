## Context
Tenant authentication currently initializes an SMS sender for every HTTP app and provides only SMS code request/verification. SaaS Lite must support password-only tenant authentication in production without Tencent credentials while retaining the current tenant cookie, CSRF, access-status, and business-route authorization boundaries.

## Goals / Non-Goals
- Goals: explicit mode selection, fail-closed disabled methods, hashed passwords, persistent brute-force protection, safe initial-password automation, authenticated self-service password rotation, and mode-aware Vue UI.
- Non-Goals: mixed SMS/password login in one deployment, password recovery, SMS-based password reset, platform-admin auth changes, or insecure HTTP production cookie exceptions.

## Decisions
- Decision: `TENANT_AUTH_MODE` accepts exactly `sms` or `password` and defaults to `sms`. Invalid values fail startup in app and worker processes so configuration drift is visible. Workers initialize neither tenant auth service nor SMS sender.
- Decision: production SMS mode preserves the existing requirements for a real Tencent sender and complete Tencent credentials. Production password mode does not construct any sender and does not require Tencent credentials; both SMS endpoints return a stable `AUTH_METHOD_DISABLED` response.
- Decision: `tenant_members` gains `password_hash`, `failed_password_attempts`, `password_locked_until`, and `password_changed_at` through a new reversible control migration. Werkzeug's password helpers provide salted one-way storage; accepted passwords contain 12 to 128 Unicode characters.
- Decision: password login looks up the normalized phone under a row lock, returns one generic error for every identity or credential failure, locks after five failures for fifteen minutes, and resets counters on success. It reuses `TenantLogin`, the tenant session cookie, and existing tenant access-status semantics.
- Decision: password change requires the current tenant cookie and matching CSRF token. A successful change updates the hash/timestamp, clears lock state, deletes every other tenant session for that member, and leaves the current session and CSRF digest intact.
- Decision: the CLI accepts a normalized-phone selector and obtains the password only from stdin when `--password-stdin` is present or from a hidden confirmed prompt otherwise. It never accepts plaintext argv/environment values, never echoes the password, and revokes all tenant sessions after setting it.
- Decision: `GET /auth/config` returns only `{method}`. The frontend loads it before choosing between the existing SMS form and the password form; both admin and operator shells link to the password-change page.

## Risks / Trade-offs
- Concurrent failed logins could otherwise lose attempt increments; row locking serializes updates on the member identity in databases that support it.
- A single generic login error reduces account-state leakage at the cost of less specific user feedback.
- Password mode intentionally disables recovery through SMS; operators must use the CLI when a member forgets a password.

## Migration Plan
1. Apply the new control migration, leaving every existing member without a password.
2. Set `TENANT_AUTH_MODE=password` and use the CLI through a non-TTY-safe stdin pipe to initialize each required member password before users sign in.
3. Restart the app. The worker may carry the same mode but never needs SMS configuration.
4. Rollback requires returning to SMS mode before downgrading; downgrade removes the four password-state columns.
