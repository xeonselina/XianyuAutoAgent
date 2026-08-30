## MODIFIED Requirements

### Requirement: Missing-order warnings are actionable
The tenant schedule SHALL render the missing-order warning only when the cached actionable order count is greater than zero.

#### Scenario: Synchronization fails with no actionable orders
- **WHEN** the latest synchronization has an error and the actionable count is zero
- **THEN** no missing-order warning SHALL be displayed

#### Scenario: Missing orders exist
- **WHEN** the actionable count is greater than zero
- **THEN** the warning SHALL show the count and allow the user to expand the actionable order list
