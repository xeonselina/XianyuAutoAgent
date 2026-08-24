# rental-damage-notes Specification

## Purpose
TBD - created by archiving change add-rental-damage-notes. Update Purpose after archive.
## Requirements
### Requirement: Store one current damage note on a rental

The system MUST store at most one current customer-reported damage note on a rental and MUST expose it in rental API responses.

#### Scenario: Operator saves a damage note
- **WHEN** an operator enters a non-empty damage note in the desktop or mobile rental editor and saves
- **THEN** the system SHALL trim and persist the note and return it as `damage_note`

#### Scenario: Operator clears a damage note
- **WHEN** an operator saves a blank or whitespace-only damage note
- **THEN** the system SHALL store `damage_note` as `null`

#### Scenario: Damage note is invalid
- **WHEN** an update provides a non-string non-null damage note or a trimmed note longer than 1000 characters
- **THEN** the system SHALL reject the request without changing the stored note

### Requirement: Edit damage notes on desktop and mobile

The system MUST let operators load, edit, and clear the current damage note from both desktop and mobile rental editing interfaces.

#### Scenario: Existing damage note is edited
- **WHEN** an operator opens a rental whose `damage_note` is non-empty
- **THEN** the editor SHALL show the current note, a danger warning, and a multiline input with a 1000-character limit

#### Scenario: Rental has no damage note
- **WHEN** an operator opens a rental whose `damage_note` is `null`
- **THEN** the editor SHALL show an empty damage-note input without a danger warning

### Requirement: Highlight customer-reported damage during inspection

The system MUST prominently display a rental's current damage note when an inspector loads that rental.

#### Scenario: Inspection rental has a damage note
- **WHEN** an inspector loads a rental with a non-empty `damage_note`
- **THEN** the rental information area SHALL display a danger alert with the full note

#### Scenario: Inspection rental has no damage note
- **WHEN** an inspector loads a rental without a damage note
- **THEN** the inspection page SHALL NOT display a damage alert

### Requirement: Require explicit inspection handling of reported damage

The system MUST append one damage-handling inspection item for a non-empty damage note and MUST initialize that item as unchecked.

#### Scenario: Dynamic checklist includes reported damage
- **WHEN** the system generates a checklist for a rental with `damage_note = "屏幕右下角碎裂"`
- **THEN** the final item SHALL be named `处理用户反馈：屏幕右下角碎裂` and SHALL have `default_checked = false`

#### Scenario: Inspector does not handle reported damage
- **WHEN** the inspector submits while the damage-handling item remains unchecked
- **THEN** the inspection record status SHALL be `abnormal`

#### Scenario: Inspector handles all items
- **WHEN** the inspector checks the damage-handling item and every other item
- **THEN** the inspection record status SHALL be `normal`

#### Scenario: Rental note later changes
- **WHEN** a damage note is edited or cleared after an inspection record was created
- **THEN** the saved inspection check-item name and checked state SHALL remain unchanged

