## ADDED Requirements

### Requirement: Tenant administrators copy model configuration safely
The model library SHALL allow a tenant administrator to create an independent model from an existing model's editable configuration without copying operational records or stable identifiers.

#### Scenario: Main-device model is copied
- **WHEN** an administrator chooses `复制` for a main-device model
- **THEN** the editor SHALL prefill its type, value, description, default accessories, package order, package states, package names, fulfillment items, and default-package selection
- **AND** the copied packages SHALL use fresh temporary identifiers that become fresh server identifiers after creation

#### Scenario: Copied model is reviewed before creation
- **WHEN** the copy editor opens
- **THEN** it SHALL suggest an unused model code derived from the source code and a copy-marked display name
- **AND** the administrator SHALL be able to edit the copied fields before saving through the normal model-create API

#### Scenario: Model configuration is copied
- **WHEN** the administrator saves a copied model
- **THEN** the system SHALL create a new model without copying source devices, rentals, usage counts, history, or source model/package identifiers

#### Scenario: Operator views the model library
- **WHEN** a tenant operator views a model row
- **THEN** copying SHALL be disabled together with the other model mutation actions

