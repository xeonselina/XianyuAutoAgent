# Change: Allow overlapping dates when creating rentals

## Why

Operators need to record a new rental even when its selected device or inventory accessory already has an overlapping schedule. The current create endpoint returns `409 DEVICE_UNAVAILABLE`, so the schedule cannot be saved.

## What Changes

- Permit schedule overlap with another rental when creating a single rental, a multi-device booking, or a booking supplement.
- Keep overlap visible in PC and mobile device selection; keep the available-slot search as a convenience for finding free equipment.
- Continue to reject invalid devices, wrong warehouses, unavailable lifecycle states, and duplicate equipment within one booking.
- Supersede the earlier `update-rental-device-selection` assumption that creation must reject occupied devices.

## Impact

- Affected spec: `rental-management`
- Affected code: rental create validation, PC and mobile creation forms, rental integration tests
