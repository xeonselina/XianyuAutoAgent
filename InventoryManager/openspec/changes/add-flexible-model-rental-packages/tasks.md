## 1. Tenant storage and migration
- [x] 1.1 Add model package configuration and rental snapshot fields.
- [x] 1.2 Seed model packages and backfill rental snapshots from legacy combination data.
- [x] 1.3 Update tenant migration head and verify upgrade/downgrade behavior.

## 2. Backend behavior
- [x] 2.1 Add package parsing, normalization, stable-ID preservation, and model validation.
- [x] 2.2 Resolve and snapshot the selected package on rental create and package-changing updates.
- [x] 2.3 Update serializers, customer history, relay comparison, and fulfillment product lines with legacy fallback.
- [x] 2.4 Add backend and migration regression coverage.

## 3. Frontend behavior
- [x] 3.1 Replace fixed checkboxes with a package editor for arbitrary names, default selection, enabled state, ordering, and fulfillment items.
- [x] 3.2 Make booking and rental editing select packages from the canonical model.
- [x] 3.3 Update history, tooltip, relay, and confirmation displays to use package snapshots.
- [x] 3.4 Add frontend regression coverage and responsive styling.

## 4. Verification and rollout
- [x] 4.1 Run focused and full backend/frontend test suites and production builds.
- [x] 4.2 Verify the model-package and booking flow in the local browser.
- [ ] 4.3 Back up production, deploy the migration and image, and verify application, worker, database, and fulfillment health.
