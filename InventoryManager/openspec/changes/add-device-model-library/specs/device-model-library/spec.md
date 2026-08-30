## ADDED Requirements

### Requirement: Tenant administrators maintain a canonical model library
The device-management workspace SHALL provide a tenant-wide model library that supports creation, editing, activation, deactivation, and safe deletion of main-device and accessory models.

#### Scenario: Model is created
- **WHEN** a tenant administrator provides a unique model code and display name
- **THEN** the model SHALL become available for device assignment

#### Scenario: Referenced model is deleted
- **WHEN** a tenant administrator attempts to delete a model assigned to one or more devices
- **THEN** the API SHALL refuse deletion and preserve the model

#### Scenario: Model is disabled
- **WHEN** a tenant administrator disables a model
- **THEN** existing devices SHALL retain the model while new device assignment SHALL exclude it

#### Scenario: Operator views the model library
- **WHEN** a tenant operator opens the model library
- **THEN** the models SHALL remain readable while all model mutations SHALL be denied

### Requirement: Device writes use canonical models
The system SHALL require an active canonical model for new devices and SHALL synchronize the legacy model name from the selected model.

#### Scenario: Device is created with an active model
- **WHEN** a tenant user creates a device with a valid active `model_id`
- **THEN** the device SHALL store that identifier and the canonical model name

#### Scenario: Device uses an inactive or missing model
- **WHEN** a tenant user submits an inactive or unknown `model_id`
- **THEN** the API SHALL reject the write without changing the device

### Requirement: Legacy free-text models can be assigned safely
The model library SHALL show unresolved free-text model groups and allow a tenant administrator to assign a group to one active canonical model.

#### Scenario: Legacy group is assigned
- **WHEN** the administrator maps one normalized free-text group to a canonical model
- **THEN** all matching unassigned devices SHALL receive the canonical `model_id` and synchronized model name atomically
