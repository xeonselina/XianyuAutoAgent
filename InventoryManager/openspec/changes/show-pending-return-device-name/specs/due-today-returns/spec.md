## ADDED Requirements

### Requirement: Show the physical machine identity for every pending return

The system MUST show the main device name, used by the store as the machine number, for every rental in the pending-return list while keeping accessory child rentals grouped under the main rental.

#### Scenario: Pending return has a named main device
- **WHEN** the system returns or renders a pending main rental whose device name is `手机-01`
- **THEN** that row SHALL show `手机-01` as its machine number together with the device model

#### Scenario: Pending return includes accessory children
- **WHEN** a pending main rental has one or more accessory child rentals
- **THEN** the system SHALL show one pending-return row for the main rental and SHALL NOT create separate rows for those accessories
