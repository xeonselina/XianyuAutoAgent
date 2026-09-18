## ADDED Requirements

### Requirement: Mark confirmed relay handoffs in pending returns

The system MUST mark a pending-return rental when it is the predecessor in a permanent relay binding and MUST NOT mark an unconfirmed relay candidate.

#### Scenario: Pending return is a confirmed relay predecessor
- **WHEN** a pending-return rental is the predecessor of a permanent relay binding
- **THEN** the API SHALL return its relay marker and successor rental ID, and the row SHALL show a visible “接力” tag

#### Scenario: Pending return is not relay-bound
- **WHEN** a pending-return rental has no permanent predecessor binding
- **THEN** the API SHALL return a false relay marker and the row SHALL NOT show the “接力” tag

#### Scenario: Relay is only an unconfirmed candidate
- **WHEN** a possible relay pair has not entered the agreed state and has no permanent binding
- **THEN** the pending-return row SHALL NOT be marked as relay
