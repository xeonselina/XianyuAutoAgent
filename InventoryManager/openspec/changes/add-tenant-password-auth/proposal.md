# Change: Add tenant password authentication compatibility mode

## Why
SaaS Lite deployments need a tenant login option that does not depend on a configured SMS provider. The option must be explicit and reversible so the existing SMS flow remains the secure default and future SMS deployments are unaffected.

## What Changes
- Add an explicit `TENANT_AUTH_MODE=sms|password` startup contract, with `sms` as the default and mode-specific production validation.
- Add password credentials, lockout state, password login, authenticated password change, and a secret-safe initial-password CLI for tenant members.
- Add a public auth configuration endpoint that exposes only the selected method, and fail closed when a disabled auth method is called.
- Add a password-aware desktop login flow and a password-change page available to tenant admins and operators.
- Add a forward/down control-database migration without modifying the shipped baseline.
- Document production password-mode setup and one-time password initialization.

## Impact
- Affected specs: `tenant-password-auth` (new capability)
- Affected code: Flask startup/configuration, control models/migrations, tenant auth API/service/CLI, Vue auth API/store/views/router/header, backend/frontend tests, SaaS deployment configuration and runbooks
