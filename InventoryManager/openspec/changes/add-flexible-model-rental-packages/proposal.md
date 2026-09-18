# Change: Add flexible rental packages to device models

## Why
The current model library only enables or disables four global Vivo lens-combination codes. That cannot represent tenant-defined camera bodies, lenses, kits, or future equipment types, and arbitrary names cannot currently be saved on a rental or rendered on fulfillment documents.

## What Changes
- Replace the fixed model lens-combination selector with model-scoped rental packages that administrators can add, rename, reorder, disable, and remove.
- Let each package define an arbitrary display name and an arbitrary fulfillment-item list with quantities, with exactly one enabled package selected as the model default.
- Save the selected package identifier plus an immutable name and fulfillment-item snapshot on each rental.
- Make booking, rental editing, customer history, relay comparison, shipping slips, and product-line generation use the selected package or its saved snapshot.
- Migrate the existing four Vivo combinations into equivalent package records without changing existing rental output.
- Keep legacy lens-combination fields readable during a compatibility period so older rentals and an application rollback remain usable.

## Impact
- Affected specs: `device-model-rental-packages`
- Affected code: tenant migrations, `DeviceModel`, `Rental`, model-library APIs and UI, booking and rental editing, relay/customer views, fulfillment product lines, mobile/shared types, regression tests, and deployment
- Data migration: every tenant database receives model package configuration and rental snapshot fields; current production data is backfilled from the existing four-value enum
