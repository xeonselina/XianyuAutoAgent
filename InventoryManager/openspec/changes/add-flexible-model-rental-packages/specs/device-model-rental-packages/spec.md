## ADDED Requirements

### Requirement: Administrators maintain arbitrary rental packages on main-device models
The model library SHALL let tenant administrators maintain an ordered set of model-scoped rental packages with arbitrary names and fulfillment items, and SHALL require exactly one enabled package to be the default.

#### Scenario: Administrator adds a camera package
- **WHEN** an administrator adds a package named `机身 + 24-70` with a camera lens and battery in its fulfillment items
- **THEN** the system SHALL preserve the package name and item quantities without requiring a global predefined combination code

#### Scenario: Administrator renames or reorders a package
- **WHEN** an administrator renames or reorders an existing package
- **THEN** the system SHALL retain its opaque identity and use the new name and order for future selection

#### Scenario: Invalid package configuration is submitted
- **WHEN** package names are duplicated, an item name is empty, an item quantity is not a positive integer, or the default is not enabled
- **THEN** the API SHALL reject the write without changing the model

#### Scenario: Accessory model is edited
- **WHEN** the model is an accessory
- **THEN** rental-package configuration SHALL be unavailable and empty

### Requirement: Rental selection uses the canonical model's enabled packages
The booking and rental-editing interfaces SHALL list enabled packages from the selected device's canonical model, and the rental API SHALL validate the selected opaque package ID against that model.

#### Scenario: Booking model changes
- **WHEN** a user selects a different canonical main-device model
- **THEN** the selector SHALL list that model's enabled packages and select its default if the prior choice is unavailable

#### Scenario: Disabled or foreign package is submitted
- **WHEN** a rental write submits a package that is disabled or belongs to another model
- **THEN** the API SHALL reject the write without changing the rental

#### Scenario: Package is changed during rental editing
- **WHEN** a user selects another enabled package while editing a rental
- **THEN** the server SHALL atomically replace the rental's package ID, name snapshot, and item snapshot

### Requirement: Rentals preserve immutable package snapshots
Each main rental SHALL preserve the selected package name and fulfillment items as an immutable snapshot independent of later model configuration changes.

#### Scenario: Package is renamed after booking
- **WHEN** an administrator renames a model package after a rental was created
- **THEN** the historical rental, customer history, and fulfillment output SHALL keep the name and items saved at booking time

#### Scenario: Package is removed after booking
- **WHEN** an administrator removes a model package after a rental was created
- **THEN** the historical rental SHALL remain readable and printable from its snapshot

#### Scenario: New rental is printed
- **WHEN** fulfillment output is generated for a rental with a package snapshot
- **THEN** it SHALL include the canonical main-device display name followed by the snapshotted package items and quantities

### Requirement: Existing lens-combination data remains compatible
The tenant migration and runtime SHALL convert existing fixed combinations to model packages and rental snapshots while retaining legacy fields and behavior as a fallback.

#### Scenario: Existing tenant is migrated
- **WHEN** a tenant with fixed Vivo lens combinations upgrades
- **THEN** its models SHALL receive equivalent packages and its existing main rentals SHALL receive equivalent name and fulfillment-item snapshots

#### Scenario: Historical rental lacks a package snapshot
- **WHEN** a historical or partially migrated rental has only a legacy `lens_combo` value
- **THEN** display, relay comparison, and fulfillment output SHALL continue to use the existing legacy mapping

#### Scenario: Application image is rolled back
- **WHEN** the deployment rolls back to the immediately previous application image after the new migration
- **THEN** the retained legacy model and rental fields SHALL still contain values readable by that image
