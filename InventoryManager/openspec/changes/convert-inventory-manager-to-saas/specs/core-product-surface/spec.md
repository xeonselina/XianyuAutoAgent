## ADDED Requirements

### Requirement: Tenant business APIs require interactive user identity
The system MUST accept tenant business APIs only through an unrevoked server-side user session, an active membership, an allowed tenant lifecycle state, and the required role permission. SaaS Core SHALL remove or disable `/external-api`, the global `X-API-Key`, tenant API keys, and every alternate machine-identity path; provider credentials MUST NOT authenticate callers to tenant APIs.

#### Scenario: Legacy global API key is presented
- **GIVEN** an old deployment value for `X-API-Key` is still present after upgrade
- **WHEN** a client calls a former external or tenant business endpoint with that key and no user session
- **THEN** the endpoint is absent or denies the request
- **AND** no tenant is resolved and no business read or write occurs

### Requirement: Removed document features have no executable surface
The system MUST remove the full Core execution path for identity-card OCR, rental contracts, and standalone single or batch shipping-order documents, including routes, navigation, API handlers, templates, static-bundle references, provider SDK/configuration, and independent download or preview endpoints. Hiding a button while retaining a callable backend SHALL NOT satisfy removal.

#### Scenario: A removed endpoint is called directly
- **GIVEN** a user knows a legacy OCR, contract, or standalone shipping-order URL
- **WHEN** the user calls it after the SaaS Core release
- **THEN** no removed business workflow executes
- **AND** no legacy credential, template, or tenant data is returned

### Requirement: Confirmed two-sheet printing remains in Core
The system MUST preserve SF ordering, tracking, batch shipping, and Kuaimai printing by expressing a print set as the SF-provided first sheet plus a locally generated return-information second sheet. The second sheet SHALL replace, rather than restore, the removed independent shipping-order document.

#### Scenario: User prints a shipment after standalone documents are removed
- **GIVEN** a valid shipment and warehouse print context
- **WHEN** the user starts the supported print flow
- **THEN** the system prints the SF first sheet and local return-information second sheet under one recorded context
- **AND** it does not create an independent shipping-order page or downloadable business document

### Requirement: Tenant branding is text-only in Core
The system MUST let an Admin configure tenant display name, legal company name, and contact details and SHALL render those values instead of hard-coded legacy company text. SaaS Core MUST NOT add company-logo upload or a general-purpose tenant file store.

#### Scenario: Tenant changes its display identity
- **GIVEN** an Admin saves valid tenant display information
- **WHEN** desktop, mobile, or the local second sheet renders tenant identity
- **THEN** the current tenant values appear
- **AND** no legacy company name or another tenant's branding is used

### Requirement: Commercial capabilities remain outside SaaS Core
The system MUST NOT expose online payment providers, billing, payment webhooks, automated refunds, financial refund state, finer plan quotas, marketing automation, tenant self-service bulk data export, or platform cross-tenant bulk business-data export as part of this Core change. Redemption codes and audited service-period adjustments SHALL remain the only confirmed Core entitlement inputs.

#### Scenario: Core operates without a payment provider
- **GIVEN** no Stripe, WeChat Pay, Alipay, or contract-billing integration is configured
- **WHEN** a tenant registers, renews, expires, or receives an audited service-period correction
- **THEN** the confirmed redemption-code and platform-adjustment paths continue to work
- **AND** no fake payment, refund, billing, or webhook record is created

