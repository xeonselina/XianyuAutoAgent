# Change: Clarify store onboarding and account navigation

## Why
The current onboarding story mixes human login credentials with Xianyu API credentials. Platform administrators need to create a customer store with a usable first administrator account, while each store administrator must own the later configuration of that store's Xianyu integration.

## What Changes
- Require the platform super administrator to set the first store administrator's phone number and initial password while creating a store.
- Define App Key and App Secret as Xianyu Steward API identity and signing credentials, not human login credentials, and keep their configuration inside the store-admin-only settings area.
- Reorganize the authenticated header so warehouse context and account actions are separate and the account menu groups identity, store settings, account security, and logout.

## Impact
- Affected specs: `store-administration`
- Affected code: platform provisioning API and UI, tenant settings UI, authenticated desktop header, provisioning/authentication tests

