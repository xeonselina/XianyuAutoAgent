# Design

## Context

The deployed implementation stores a list of four global codes on each `device_models` row and persists one of those codes in the `rentals.lens_combo` enum. Product-line generation then expands that enum through hard-coded Vivo-specific rules. A free-text input alone would allow a new label but would still leave validation, historical orders, relay checks, and shipping content tied to the fixed enum.

## Goals / Non-Goals

- Goals:
  - Support arbitrary package names per main-device model.
  - Support arbitrary package contents so a phone lens kit, camera lens kit, or another equipment type follows the same workflow.
  - Keep historical rental and fulfillment output stable after a package is renamed or removed.
  - Preserve a safe rollback path to the current deployed application.
- Non-Goals:
  - Share one package definition across different models.
  - Turn package items into individually inventoried accessory devices.
  - Remove the legacy lens-combination columns in this release.

## Decisions

### Model package storage

- Add `rental_packages` JSON text and `default_rental_package_id` string fields to `device_models`.
- A package has a server-generated opaque ID, administrator-controlled name, enabled state, order, and zero or more fulfillment items of `{name, qty}`.
- Main-device models MUST have at least one enabled package and exactly one enabled default. Accessory models have no rental packages.
- Package names are unique within one model after trimming and case-folding. Item names are non-empty and quantities are positive integers.
- Deleting a package only removes it from future selection. Existing rental snapshots remain intact.

This nested configuration is intentionally stored with the model because packages are small, always edited as one model-scoped document, and do not need independent querying. Opaque package IDs preserve identity across renames.

### Rental selection and snapshots

- Add nullable `rental_package_id`, `rental_package_name`, and `rental_package_items` JSON text fields to `rentals`.
- New rental writes submit `rental_package_id`. The server resolves it against the selected device's canonical model, requires it to be enabled, and copies the package name and fulfillment items into the rental snapshot.
- Rental edits that change the package refresh all three snapshot fields. Other edits leave the snapshot unchanged.
- API responses expose a `rental_package` object built from the snapshot. Existing `lens_combo` remains available for compatibility but is not used by the new UI.

### Fulfillment and downstream behavior

- Product-line generation always includes the canonical model display name as the main item, then appends the rental's snapshotted fulfillment items.
- Customer history and tooltips display the snapshotted package name.
- Relay checks compare opaque package IDs when both rentals use packages and fall back to legacy enum comparison for older rentals.
- Historical rentals without snapshots continue to use the current fixed-enum display and product-line rules.

### Migration compatibility

- Seed every main-device model with packages equivalent to its current `allowed_lens_combos` configuration.
- Map the four legacy codes to the existing labels and exact fulfillment output:
  - `lens_400mm`: charger, 400MM kit, carrying bag.
  - `lens_200mm`: charger, 200MM kit, carrying bag.
  - `bare`: charger only.
  - `lens_dual`: charger, both lens kits, carrying bag.
- Backfill every main rental with a stable migrated package ID plus name/items snapshot based on its canonical model and saved enum. Child accessory rentals do not receive packages.
- Keep `allowed_lens_combos`, `default_lens_combo`, and `rentals.lens_combo` unchanged during this release. A rollback therefore continues to read the old fields.

## Risks / Trade-offs

- JSON storage cannot enforce nested uniqueness at the database layer. Service validation is authoritative and covered by API tests.
- Removing a package from the model could otherwise make historical records ambiguous. Immutable rental snapshots eliminate that dependency.
- During the compatibility window, old and new fields coexist. Serializers and tests define which one is authoritative for each path.

## Rollout Plan

1. Add and test the tenant migration and backfill against representative SQLite and MariaDB tenant schemas.
2. Deploy backend compatibility first in the same image as the new frontend.
3. Back up production immediately before tenant migration.
4. Run the migration, deploy the image, and verify model editing, booking, history, relay, printing, and health checks.
5. Retain the previous image and legacy columns for rollback.

## Open Questions

- None. Package contents are fulfillment text and quantities, not separately tracked inventory, which matches the current shipping-product-line behavior.
