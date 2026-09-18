## Context
Tenant authentication currently initializes an SMS sender for every HTTP app and provides only SMS code request/verification. SaaS Lite must support password-only tenant authentication in production without Tencent credentials while retaining the current tenant cookie, CSRF, access-status, and business-route authorization boundaries.

## Goals / Non-Goals
- Goals: explicit mode selection, fail-closed disabled methods, hashed passwords, persistent brute-force protection, safe initial-password automation, authenticated self-service password rotation, and mode-aware Vue UI.
- Non-Goals: mixed SMS/password login in one deployment, password recovery, SMS-based password reset, platform-admin auth changes, or insecure HTTP production cookie exceptions.

## Decisions
- Decision: `TENANT_AUTH_MODE` accepts exactly `sms` or `password` and defaults to `sms`. Invalid values fail startup in app and worker processes so configuration drift is visible. Workers initialize neither tenant auth service nor SMS sender.
- Decision: production SMS mode preserves the existing requirements for a real Tencent sender and complete Tencent credentials. Production password mode does not construct any sender and does not require Tencent credentials; both SMS endpoints return a stable `AUTH_METHOD_DISABLED` response.
- Decision: `tenant_members` gains `password_hash`, `failed_password_attempts`, `password_locked_until`, and `password_changed_at` through a new reversible control migration. Werkzeug's password helpers provide salted one-way storage; accepted passwords contain 8 to 128 Unicode characters.
- Decision: password login acquires a bounded MariaDB advisory lock derived from the normalized phone before looking up any identity or checking its hash. Existing and unknown same-phone candidates therefore serialize alike, while the member row lock keeps updates defensive. Lock timeout returns the same generic failure. Invalid phone syntax still performs the dummy Werkzeug verification. Five failures lock for fifteen minutes and success resets counters. Login reuses `TenantLogin`, the tenant session cookie, and existing tenant access-status semantics.
- Decision: password change requires the current tenant cookie and matching CSRF token. A successful change updates the hash/timestamp, clears lock state, deletes every other tenant session for that member, and leaves the current session and CSRF digest intact.
- Decision: the CLI accepts a normalized-phone selector and obtains the password only from stdin when `--password-stdin` is present or from a hidden confirmed prompt on a real TTY. Without either condition it fails before reading a secret, avoiding `getpass` fallback warnings or terminal echo. It never accepts plaintext argv/environment values, never echoes the password, and revokes all tenant sessions after setting it.
- Decision: `GET /auth/config` returns only `{method}`. The frontend loads it before choosing between the existing SMS form and the password form; configuration failure renders no credential form and offers an explicit retry. Both admin and operator shells link to the password-change page, whose Flask SPA fallback supports direct navigation and refresh.

## Risks / Trade-offs
- Per-phone advisory locking holds an expensive hash operation and can briefly queue same-candidate requests; a bounded timeout fails generically, while distinct phones retain independent locks. This closes the concurrent timing distinction for unknown identities and keeps failed-attempt updates atomic.
- A single generic login error reduces account-state leakage at the cost of less specific user feedback.
- Password mode intentionally disables recovery through SMS; operators must use the CLI when a member forgets a password.

## Migration Plan
1. Apply the new control migration, leaving every existing member without a password.
2. Set `TENANT_AUTH_MODE=password` and use the CLI through a non-TTY-safe stdin pipe to initialize each required member password before users sign in.
3. Restart the app. The worker may carry the same mode but never needs SMS configuration.
4. Ordinary rollback between password-capable tags may use `previous.env` and `deploy-nas`. After the shared `app.env` switches to password mode, it MUST NOT be used unchanged to start a pre-password-auth image. An upgrade from a real configured SMS release must retain that release's existing root-only SMS environment with valid Tencent credentials and `TENANT_AUTH_MODE=sms` before switching modes. This first NAS deployment has neither valid Tencent credentials nor a Compose previous tag, must not fabricate credentials, and can recover backward only by restarting the separately stopped legacy container with its original environment until the first password-capable tag is established. Schema downgrade removes the four password-state columns only under an explicit recovery plan.
