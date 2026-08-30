# Design

## Context

Rentals already persist one of four stable `lens_combo` enum values: `lens_400mm`, `lens_200mm`, `bare`, or `lens_dual`. Only the per-model allowed set and default value are incorrectly embedded in code.

## Decisions

- Add `allowed_lens_combos` JSON text and `default_lens_combo` string fields to `device_models`.
- Only main-device models can configure lens combinations. Accessory models expose no combination settings.
- Model API writes validate that every value is one of the four existing rental enum values and that the default belongs to the allowed set.
- The booking selector receives the selected `DeviceModel` object and renders its allowed/default values instead of importing a model-name map.
- Rental handlers resolve the canonical `DeviceModel` from the selected device and validate against that row. Legacy devices without `model_id` retain a compatibility fallback.
- Combination display labels and shipping product-line semantics remain global because they describe the persisted rental enum, not a tenant model.
- Printed main-device names use the canonical model display name when available rather than another model-name map.

## Migration Plan

- Add the two nullable fields to every tenant database.
- Seed X200U and X300 Pro with `lens_200mm` plus `bare`, defaulting to `lens_200mm`.
- Seed X300U with all four combinations, defaulting to `lens_400mm`.
- Seed other main-device models with `lens_200mm` plus `bare`, defaulting to `lens_200mm`, matching the current frontend fallback.
- Leave accessory models empty.

## Risks / Trade-offs

- This change deliberately does not create arbitrary new combination codes. Adding new shipping composition types would also require changing the rental enum and product-line rules and should be a separate change.
- Existing rentals keep their saved combination value, so later model configuration changes affect only new or edited rental selection and validation.
