## ADDED Requirements

### Requirement: Show the renter in the pending-return contact column

The system MUST show the main rental's customer name and phone number together in the contact column for every pending-return row.

#### Scenario: Pending return has a customer name and phone
- **WHEN** the user opens the pending-return list for a rental with a customer name and phone number
- **THEN** the contact column SHALL show both the customer name and phone number

### Requirement: Recover a pending-return status action after CSRF rotation

The system MUST recover a pending-return status action once when the current page holds a rotated CSRF token.

#### Scenario: First status request has an invalid CSRF token
- **WHEN** marking a rental returned receives `CSRF_INVALID`
- **THEN** the client SHALL refresh the current tenant session and retry that status request exactly once

#### Scenario: Retried request still fails
- **WHEN** the retried status request fails
- **THEN** the client SHALL keep the pending-return row, clear its loading state, show the returned error, and SHALL NOT retry again

#### Scenario: Status request fails for another reason
- **WHEN** marking a rental returned fails with an error other than `CSRF_INVALID`
- **THEN** the client SHALL show that error without refreshing the session or retrying the request
