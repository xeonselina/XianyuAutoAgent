## ADDED Requirements

### Requirement: Tenant users can administer devices in one workspace
The device management workspace SHALL list devices for the selected warehouse and support search, lifecycle and type filters, creation, editing, movement, and deletion.

#### Scenario: All warehouses are selected
- **WHEN** the tenant user views all warehouses
- **THEN** the device list SHALL remain readable and all mutation actions SHALL be disabled with guidance to select a concrete warehouse

#### Scenario: Device is deleted
- **WHEN** the user confirms deletion for a device without rental history
- **THEN** the device SHALL be deleted and the list SHALL refresh

#### Scenario: Device has rental history
- **WHEN** the user attempts to delete a device with rental history
- **THEN** the API SHALL refuse deletion and preserve the device

### Requirement: Device search covers operational identifiers
The device list API SHALL support one search term across device name, serial number, and model.

#### Scenario: User searches by serial number fragment
- **WHEN** a serial number fragment is supplied as `q`
- **THEN** matching devices SHALL be returned even when their names do not contain that fragment
