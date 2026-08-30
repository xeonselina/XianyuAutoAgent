## Context
Password authentication is already available for tenant members, but the member-management workflow only creates an identity record. As a result, members created inside a tenant cannot authenticate until an operator uses an out-of-band CLI.

## Goals / Non-Goals
- Goals: make every newly created member immediately login-capable, support administrator resets, use one password policy everywhere, and preserve tenant/session boundaries.
- Non-Goals: display or recover plaintext passwords, add password history, or allow operators to administer other members' credentials.

## Decisions
- Decision: tenant passwords contain 8 through 128 Unicode characters. The same backend validator is used for platform onboarding, CLI initialization, self-change, member creation, and member reset.
- Decision: member creation receives `initial_password`, hashes it inside the same control-store transaction as the new member, and never returns it.
- Decision: `PUT /api/settings/members/<id>/password` is administrator-only, accepts `new_password`, resets failed-login state, and deletes every tenant authentication session for that member.
- Decision: the UI asks for password confirmation locally, but only the password is sent to the server.

## Risks / Trade-offs
- Eight-character passwords are weaker than the former twelve-character minimum. The system retains the 128-character maximum, salted password hashing, login lockout, and session revocation to reduce risk.
- Resetting the currently signed-in administrator's own password through member management will revoke that session. The UI directs users to the self-service password page for their own credential and uses administrative reset for managed members.

## Migration Plan
No schema migration is required. Deploy backend and frontend together so the newly required member-creation field is available immediately.

## Open Questions
- None.
