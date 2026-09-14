# Change: Add tenant member password management

## Why
Tenant administrators can add members, but newly created members have no password and therefore cannot sign in while password authentication is enabled. Administrators also need a safe way to replace a member's password when it is forgotten.

## What Changes
- Require an administrator to enter and confirm an initial password when creating a tenant member.
- Let tenant administrators reset an existing member's password from member settings.
- Apply the requested 8-to-128-character password policy consistently to tenant provisioning, member creation, self-service password changes, and administrative resets.
- Store only password hashes, clear lockout state after a reset, and revoke the reset member's existing sessions.

## Impact
- Affected specs: `tenant-password-auth`, new `tenant-member-password-management`
- Affected code: tenant auth policy, settings service/API, member settings UI, platform onboarding UI, password-change UI, and related tests
- API compatibility: creating a member now requires `initial_password`; a new administrator-only member password endpoint is added
