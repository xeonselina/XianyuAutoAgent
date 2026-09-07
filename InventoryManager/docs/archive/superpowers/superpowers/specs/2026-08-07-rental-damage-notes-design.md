# Rental Damage Notes Design

## Goal

Allow operators to record one current customer-reported damage note on a rental and ensure the inspector sees and explicitly handles that report during inspection.

## Scope

- Add one nullable `damage_note` field to the main rental record.
- Allow the field to be edited and cleared from both desktop and mobile rental editing flows.
- Highlight a non-empty note on the existing responsive inspection page.
- Append a default-unchecked inspection item that snapshots the reported damage text.
- Keep completed inspection records unchanged when the rental note is later edited or cleared.

The feature does not add damage-report history, a repair workflow, a device lifecycle transition, or a separate mobile inspection route.

## Data Model and API

`rentals.damage_note` is a nullable `TEXT` column. Existing records migrate to `NULL`. The field belongs to the rental being edited and is not copied to accessory child rentals.

`Rental.to_dict()` always returns `damage_note`, using `null` when there is no report. The existing rental update endpoints accept a string or `null`. The handler trims surrounding whitespace, converts a blank string to `null`, and rejects non-string values or values longer than 1000 characters with HTTP 400 before mutating the rental.

Creation flows do not expose or submit the field. Completing an inspection does not clear the note; operators clear it through rental editing when appropriate.

## Desktop and Mobile Editing

The desktop edit dialog adds a dedicated damage-feedback section with a multiline input, a 1000-character counter, and a danger alert while the note is non-empty. It loads the current API value and includes `damage_note` in the existing update payload.

The mobile edit view provides the same field, counter, warning, initialization, and update payload using Vant components. Layout remains touch-friendly for phones and iPad.

## Inspection Flow

When the existing inspection lookup returns a rental with a non-empty `damage_note`, the rental information card displays a prominent danger alert containing the full note.

`ChecklistGenerator` appends one final item named `处理用户反馈：{damage_note}` with `default_checked: false`. Other generated items remain checked by default. The inspection store initializes each item from `default_checked`, falling back to `true` for compatibility with older API responses.

If the inspector submits without checking the damage item, the existing status calculation records the inspection as `abnormal`. Checking it allows the normal all-items-checked result. The submitted check-item name is stored in `inspection_check_item`, preserving the original report text even if the rental note later changes.

## Error Handling

- `damage_note` of a type other than string or `null` returns HTTP 400.
- A trimmed note longer than 1000 characters returns HTTP 400 and does not change the stored note.
- A blank or whitespace-only note is stored as `NULL` and removes the warning and generated item.
- Database failures use the existing rollback and unified server-error response.

## Testing

- Backend model/API tests cover serialization, save, trim, update, clear, invalid type, and length rejection.
- Checklist tests cover absence for blank notes, final ordering, exact text, and `default_checked: false`.
- Desktop component/store tests cover loading and submitting the note plus inspection warning/default state.
- Mobile edit E2E coverage verifies loading and submitting the note.
- Verification includes focused tests, backend regression tests, desktop tests/build, mobile E2E or equivalent focused coverage, mobile build, migration head checks, and strict OpenSpec validation.

