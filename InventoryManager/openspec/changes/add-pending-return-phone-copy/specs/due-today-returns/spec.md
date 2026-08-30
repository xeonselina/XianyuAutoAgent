## ADDED Requirements

### Requirement: Copy a pending-return phone number

The system MUST provide an icon-only copy action beside each available phone number in the pending-return list and MUST copy only that row's phone number.

#### Scenario: Clipboard API is available
- **WHEN** the user clicks the copy icon beside a phone number and the Clipboard API succeeds
- **THEN** the system SHALL copy the exact phone number and show a success message

#### Scenario: Clipboard API is unavailable on HTTP
- **WHEN** the user clicks the copy icon while the Clipboard API is unavailable
- **THEN** the system SHALL attempt a compatible fallback copy and show the corresponding success or failure message

#### Scenario: Rental has no phone number
- **WHEN** a pending-return row has no customer phone number
- **THEN** the system SHALL show the existing empty value and SHALL NOT show a copy icon for that row
