## Context
Tenant members authenticate with a mainland-China phone number and password. Xianyu integration credentials are consumed by backend requests to the Xianyu Steward API and are unrelated to the member session.

## Goals / Non-Goals
- Goals: make a newly provisioned store immediately login-ready; keep human and API credentials distinct; make the account menu predictable.
- Non-Goals: add self-registration, expose stored App Secrets, or change tenant role semantics.

## Decisions
- The platform create-store request accepts a 12–128 character initial password. The backend hashes it before the first control-database write and never returns it.
- The first member is an active store administrator identified by the supplied phone number. Existing password-login and password-change flows are reused.
- App Key identifies the store's API connection and App Secret signs API requests. Only store administrators can configure them; the secret remains encrypted and non-readable after saving.
- The header presents the active store and warehouse separately from a single account menu. Administrative settings are omitted for operators.

## Risks / Trade-offs
- A platform administrator necessarily handles an initial password once. The UI does not retain it after successful creation, and the API never echoes it.
- Native menu disclosure behavior is intentionally simple and keyboard-accessible; richer interaction can be added later without changing the information architecture.

## Migration Plan
No schema migration is required because tenant members already have password fields and Xianyu credentials already use encrypted storage. Deploy the new app image after the normal control/tenant migration checks and retain the prior image for rollback.

