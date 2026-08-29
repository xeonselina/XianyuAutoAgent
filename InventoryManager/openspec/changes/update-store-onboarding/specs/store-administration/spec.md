## ADDED Requirements

### Requirement: Platform-created first store administrator
The platform super administrator MUST provide a store name, first administrator phone number, 12–128 character initial password, and service expiration when creating a customer store. The system MUST normalize the phone number, persist only a password hash, create the first member as an active store administrator, and MUST NOT return the plaintext password or password hash in any tenant response.

#### Scenario: Newly created administrator can use password login
- **WHEN** a platform super administrator creates a store with valid initial administrator credentials and provisioning succeeds
- **THEN** the supplied phone and initial password authenticate the active store administrator through the normal tenant password-login flow

#### Scenario: Invalid initial password is rejected atomically
- **WHEN** the initial password is missing, shorter than 12 characters, or longer than 128 characters
- **THEN** the create-store request fails before any tenant or member row is created

### Requirement: Store-owned Xianyu API credentials
Only a store administrator MUST be able to configure that store's Xianyu Steward App Key and App Secret. The interface MUST explain that the App Key identifies the store's API connection and the App Secret signs order-query and shipment requests, and that neither value is a site login password, Xianyu account password, or cookie. The App Secret MUST be encrypted at rest and MUST NOT be returned after saving.

#### Scenario: Store administrator configures a Xianyu shop
- **WHEN** an authenticated store administrator opens the Xianyu API settings and saves credentials for a shop
- **THEN** the system associates the credentials with that store and subsequently shows only whether an App Secret is configured

#### Scenario: Operator cannot administer Xianyu credentials
- **WHEN** an authenticated operator attempts to open or call the Xianyu credential settings
- **THEN** the interface omits the action and the API denies the request

### Requirement: Organized authenticated account menu
The authenticated desktop shell MUST show store identity and active warehouse context separately from account actions. A single account menu MUST identify the current member and role, group store settings for administrators, provide account security for both roles when password authentication is enabled, and provide logout.

#### Scenario: Store administrator opens the account menu
- **WHEN** an authenticated store administrator opens the account menu
- **THEN** the menu shows their identity, store settings with team and Xianyu API guidance, account security, and logout in distinct groups

#### Scenario: Operator opens the account menu
- **WHEN** an authenticated operator opens the account menu
- **THEN** the menu shows identity, account security when enabled, and logout without any store-administration entry
