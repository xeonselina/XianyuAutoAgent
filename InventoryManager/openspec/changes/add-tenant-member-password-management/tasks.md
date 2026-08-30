## 1. Specification
- [x] 1.1 Validate the member password management proposal and security scenarios strictly.

## 2. Backend
- [x] 2.1 Change the shared tenant password policy to 8 through 128 characters and update safe user-facing errors.
- [x] 2.2 Require and hash an initial password when an administrator creates a member.
- [x] 2.3 Add an administrator-only password reset endpoint that clears lockout state and revokes the member's sessions.

## 3. Frontend
- [x] 3.1 Add initial-password and confirmation controls to member creation.
- [x] 3.2 Add a member password-reset flow with matching policy validation and clear success messaging.
- [x] 3.3 Update platform onboarding and self-service password guidance to the 8-character minimum.

## 4. Verification and rollout
- [x] 4.1 Add backend and frontend regression coverage for password creation, reset, policy, authorization, and secret-safe responses.
- [x] 4.2 Run strict OpenSpec validation, focused/full tests, typecheck, build, and static checks.
- [ ] 4.3 Commit and deploy the verified image, confirm production health, and update the local maintenance context without secrets.
