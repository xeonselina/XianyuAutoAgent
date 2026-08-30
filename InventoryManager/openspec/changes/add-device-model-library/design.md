# Design

## Context

`device_models` already stores canonical names, display names, descriptions, values, accessory relationships, and activation state. Devices also retain a legacy free-text `model` field, and existing readers fall back to that value when `model_id` is absent.

## Decisions

- The model library is tenant-wide rather than warehouse-specific because model identity and valuation must remain consistent across warehouses.
- The canonical `name` is a normalized stable code. `display_name` remains user-editable.
- Device writes select `model_id`; the API synchronizes the legacy `model` field to the canonical name for backward compatibility.
- Referenced models cannot be deleted. They can be disabled so historical devices and rentals remain readable.
- Legacy groups are devices with no `model_id`, grouped by trimmed free-text model. Assignment updates the entire selected group atomically.
- Accessory models may reference one parent model using the existing `parent_model_id` relationship. Parent selection is cleared for main-device models.

## Risks / Trade-offs

- Some older statistics code still accepts model names. Synchronizing the legacy field during assignment preserves those paths while canonical IDs become authoritative.
- Hard deletion is limited to unreferenced models to protect historical joins.

## Migration Plan

No schema migration is required. Existing model rows and devices remain valid. Tenant administrators can progressively resolve legacy groups from the new model-library page.
