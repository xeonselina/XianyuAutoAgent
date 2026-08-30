# Change: Add device-model copying

## Why
Tenant administrators often add closely related equipment models whose value, accessories, and rental packages differ only slightly. Re-entering every package and fulfillment item is slow and error-prone.

## What Changes
- Add a `复制` action to each model-library row for tenant administrators.
- Open the existing model editor in copy mode with the source model's editable configuration prefilled.
- Suggest an unused model code derived from `<source>-copy` and a display name marked as a copy, while keeping both editable before save.
- Deep-copy rental packages and fulfillment items with fresh client/server package IDs so the new model is independent of the source.
- Never copy devices, rentals, usage counts, history, or any relationship other than an accessory model's selected parent model.

## Impact
- Affected specs: `device-model-library`
- Affected code: `frontend/src/components/DeviceModelLibrary.vue` and its component tests
- API/schema impact: none; saving continues to use `POST /api/device-models`

