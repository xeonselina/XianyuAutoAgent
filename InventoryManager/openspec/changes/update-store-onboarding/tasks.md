## 1. Store onboarding
- [x] 1.1 Require and validate an initial administrator password in the platform create-store API.
- [x] 1.2 Hash the password and attach it to the first active store administrator during provisioning.
- [x] 1.3 Add initial-password and confirmation fields to the platform create-store form.

## 2. Store administration UI
- [x] 2.1 Explain App Key and App Secret and keep their configuration in the admin-only Xianyu API settings.
- [x] 2.2 Reorganize the authenticated header into store context, warehouse context, and an account menu.
- [x] 2.3 Hide store-administration actions from operators while retaining account security and logout.

## 3. Verification and rollout
- [x] 3.1 Add backend coverage for password validation and hashed persistence.
- [x] 3.2 Add frontend coverage for create-store validation and request serialization.
- [ ] 3.3 Run full regression checks and deploy the production image with rollback metadata.

