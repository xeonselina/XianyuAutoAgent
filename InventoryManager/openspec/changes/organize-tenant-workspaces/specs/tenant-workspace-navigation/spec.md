## ADDED Requirements

### Requirement: Tenant users can navigate by business workspace
The authenticated tenant header SHALL expose schedule, device management, statistics, and receiving/shipping as four primary destinations.

#### Scenario: Nested operation route stays grouped
- **WHEN** a tenant user opens batch shipping, inspection, relay management, or logistics tracking
- **THEN** the receiving/shipping destination SHALL remain the active primary workspace

### Requirement: Schedule actions stay schedule-specific
The schedule workspace SHALL expose booking, customer history, pending returns, refresh, and one-click schedule reorder without exposing inventory, statistics, or shipping destinations in its action menu.

#### Scenario: User opens the schedule action menu
- **WHEN** the user opens the schedule action menu
- **THEN** only customer history on compact screens, refresh, and one-click reorder SHALL be offered

### Requirement: Tenant context remains compact
The authenticated tenant header SHALL present store, warehouse, primary navigation, and account access in one compact row.

#### Scenario: Desktop header renders
- **WHEN** an authenticated tenant page is displayed on a desktop viewport
- **THEN** the header SHALL use a 42-pixel minimum height and the route content SHALL use the remaining viewport
