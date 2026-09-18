## ADDED Requirements

### Requirement: Discoverable platform store dashboard
The application MUST provide a separately authenticated super-administrator dashboard for customer stores and MUST expose a low-emphasis link to the independent platform login from the store login page. The dashboard MUST summarize total, active, suspended, and provisioning-problem stores and MUST retain store lifecycle controls.

#### Scenario: Super administrator enters platform management
- **WHEN** a user follows the super-administrator entry and completes platform password plus TOTP authentication
- **THEN** they arrive at the customer-store dashboard without creating or reusing a tenant session

### Requirement: Explained first-administrator onboarding form
The platform dashboard MUST provide a create-store panel for store name, initial administrator phone, initial password and confirmation, and service expiry. It MUST explain that the initial password is for human store login, is not an App Key or App Secret, is stored only as a hash, and is not returned.

#### Scenario: Super administrator creates a customer store
- **WHEN** valid onboarding fields are submitted
- **THEN** the existing secure create-store API provisions the store and the new store appears in the lifecycle list
