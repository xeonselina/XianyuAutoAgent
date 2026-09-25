# Change: Allow warned conflicts when editing rental devices

## Why

Operators sometimes need to swap devices between two existing rentals. The first edit temporarily overlaps the other rental, so the current save validation prevents the swap even after the editor warns about the conflict. Device lists are also hard to scan when their order depends on API results.

## What Changes

- Allow an existing rental to be saved with a time overlap after a visible conflict warning. Keep creation conflict checks and all non-scheduling device validation.
- Sort device dropdown options by model, then device name, in PC and mobile rental creation and editing.

## Impact

- Affected capability: rental device selection and editing.
- Affected code: rental service, PC and mobile rental editors and selectors, and their tests.
