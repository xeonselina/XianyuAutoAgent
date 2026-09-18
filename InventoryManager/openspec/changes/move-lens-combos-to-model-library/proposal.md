# Change: Move lens-combo configuration into the model library

## Why
Allowed and default lens combinations for X200U, X300 Pro, and X300U are duplicated as hard-coded frontend and backend maps. Tenant administrators cannot maintain them, and the two copies can drift.

## What Changes
- Add allowed lens combinations and one default combination to canonical main-device models.
- Add lens-combo controls to the model-library editor.
- Make booking selection and server-side rental validation use the selected canonical model configuration.
- Keep the four existing rental combination codes and their shipping product-line meaning unchanged.
- Seed existing model rows with the current X200U, X300 Pro, and X300U behavior during tenant migration.

## Impact
- Affected specs: `device-model-lens-combos`
- Affected code: tenant migration, `DeviceModel`, model-library APIs and UI, booking lens selector, rental validation, printing tests
