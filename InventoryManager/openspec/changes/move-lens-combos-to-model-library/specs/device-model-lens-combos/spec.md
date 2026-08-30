## ADDED Requirements

### Requirement: Administrators maintain lens combinations on main-device models
The model library SHALL let tenant administrators select the allowed lens combinations and exactly one default combination for each main-device model.

#### Scenario: Administrator edits a main-device model
- **WHEN** the administrator selects one or more supported lens combinations and chooses a default among them
- **THEN** the model SHALL persist that allowed set and default

#### Scenario: Invalid default is submitted
- **WHEN** the submitted default is absent from the model's allowed set
- **THEN** the API SHALL reject the update without changing the model

#### Scenario: Accessory model is edited
- **WHEN** the model is an accessory
- **THEN** lens-combination configuration SHALL be unavailable and empty

### Requirement: Rental selection uses canonical model configuration
The booking UI and rental API SHALL derive allowed and default lens combinations from the canonical model assigned to the selected device.

#### Scenario: Booking model changes
- **WHEN** a user selects a different canonical device model
- **THEN** the selector SHALL show that model's allowed combinations and choose its configured default if the previous choice is invalid

#### Scenario: Disallowed combination is submitted
- **WHEN** a rental write contains a combination not allowed by the device's canonical model
- **THEN** the API SHALL reject the write without changing the rental

#### Scenario: Existing rental is displayed
- **WHEN** a historical rental has a persisted combination that is no longer enabled on the model
- **THEN** customer history, relay warnings, and shipping output SHALL continue to display the persisted combination

### Requirement: Existing model behavior is migrated safely
The tenant migration SHALL seed existing canonical models with combination behavior compatible with the previous hard-coded configuration.

#### Scenario: Known model is migrated
- **WHEN** an existing X200U, X300 Pro, or X300U canonical model is migrated
- **THEN** its allowed and default combinations SHALL match the previous application behavior

#### Scenario: Other main-device model is migrated
- **WHEN** an existing main-device model has no known hard-coded configuration
- **THEN** it SHALL receive the compatibility default of 200MM plus bare-machine options with 200MM selected by default
