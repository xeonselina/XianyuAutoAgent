## 1. Specification and tests
- [x] 1.1 Strictly validate the OpenSpec proposal and auth-mode/security scenarios.
- [x] 1.2 Add focused backend tests for configuration, password policy/login/lockout/reset, sessions/CSRF, disabled methods, CLI secret handling, and migration structure.
- [x] 1.3 Add focused frontend tests for mode-specific login, password change, CSRF preservation, routing, and navigation visibility.

## 2. Backend implementation
- [x] 2.1 Add and validate `TENANT_AUTH_MODE`, preserving SMS production requirements while allowing password-mode production startup without Tencent credentials and keeping workers sender-free.
- [x] 2.2 Add a reversible control migration and matching `TenantMember` password/lockout fields without changing the baseline.
- [x] 2.3 Implement password login, persistent lockout/reset behavior, authenticated CSRF-protected password change, and other-session revocation.
- [x] 2.4 Implement and register a normalized-phone, stdin/hidden-prompt tenant password CLI that revokes existing sessions without exposing plaintext.

## 3. Frontend implementation
- [x] 3.1 Add auth config, password login/change API calls, and auth-store actions that retain the active CSRF header.
- [x] 3.2 Render the password form only in password mode while preserving the SMS login form in SMS mode.
- [x] 3.3 Add an authenticated password-change page, router entry, and AppHeader link for admin and operator roles.

## 4. Operations and verification
- [x] 4.1 Update `.env.example` and SaaS deployment documentation for password mode, safe one-time initialization, and public-image registry login behavior.
- [x] 4.2 Run strict OpenSpec validation, focused backend/frontend tests, frontend typecheck/build, migration/static checks, `git diff --check`, and a secret-pattern scan.
- [x] 4.3 Commit the complete scoped implementation while preserving existing NAS automation work.

## 5. Review hardening
- [x] 5.1 Serialize normalized password candidates with a hashed MariaDB advisory lock and cover unknown/existing concurrency plus timeout behavior.
- [x] 5.2 Add the password-change SPA fallback, non-TTY CLI refusal, and fail-closed auth-config retry UI with regressions.
- [x] 5.3 Document the pre-password-image rollback compatibility boundary and preserve ordinary rollback between password-capable tags.
