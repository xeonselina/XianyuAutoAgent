## ADDED Requirements

### Requirement: Unified tenant password policy
The system MUST accept tenant passwords containing 8 through 128 characters for platform onboarding, member creation, administrative reset, CLI initialization, and authenticated self-service change. Invalid passwords MUST be rejected before credentials or sessions are changed.

#### Scenario: Eight-character password is accepted
- **WHEN** an authorized workflow submits an eight-character tenant password
- **THEN** the password passes the shared policy validation

#### Scenario: Seven-character password is rejected
- **WHEN** an authorized workflow submits a seven-character tenant password
- **THEN** the system returns a safe policy error and changes neither credentials nor sessions

### Requirement: Administrator-defined initial member password
A tenant administrator MUST provide an initial password when adding a member. The system MUST normalize the phone, store only a salted password hash with the new member, initialize the password-change timestamp, and MUST NOT return the plaintext password or hash.

#### Scenario: Administrator creates a login-capable member
- **WHEN** an administrator adds a unique member phone, role, and policy-compliant initial password
- **THEN** the member is created with a password hash and can use password authentication

#### Scenario: Initial password is missing
- **WHEN** an administrator attempts to add a member without an initial password
- **THEN** the request fails without creating the member

### Requirement: Administrator member password reset
A tenant administrator MUST be able to replace an existing member's password within the same tenant. Success MUST store only the new salted hash, update the password-change timestamp, clear failed-attempt and lock state, and revoke all tenant sessions belonging to that member.

#### Scenario: Administrator resets a member password
- **WHEN** an administrator submits a policy-compliant new password for a member in the same tenant
- **THEN** the password is replaced, lock state is cleared, all of that member's sessions are revoked, and no password material is returned

#### Scenario: Operator attempts a reset
- **WHEN** an operator submits a member password reset request
- **THEN** the system denies the request and changes neither credentials nor sessions

#### Scenario: Administrator targets another tenant
- **WHEN** an administrator submits a reset for an identifier that does not belong to the current tenant
- **THEN** the system returns the same not-found result as an unknown identifier and changes nothing
