## ADDED Requirements

### Requirement: Warn on overlapping device selections while editing
The system SHALL permit an existing rental to be saved when its selected device overlaps another rental, after showing the operator a conflict warning. Device existence, warehouse, lifecycle, and booking compatibility validation SHALL remain in force. New rental creation SHALL continue to reject occupied devices.

#### Scenario: Swap devices between two rentals
- **WHEN** an operator changes the first rental to the second rental's device for an overlapping period and confirms the warning
- **THEN** the first edit saves, so the operator can complete the swap by editing the second rental

#### Scenario: Creating a rental with an occupied device
- **WHEN** an operator creates a new rental using a device occupied by another rental in that period
- **THEN** the create request is rejected without saving a conflicting rental

### Requirement: Order rental device options
The system SHALL list device choices in ascending natural order by device model and then by device name in PC and mobile rental creation and editing.

#### Scenario: Models and names contain numbers
- **WHEN** a device list contains model X2 and X10 and devices named Camera 2 and Camera 10 within one model
- **THEN** X2 appears before X10 and Camera 2 appears before Camera 10
