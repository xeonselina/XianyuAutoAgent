# Change: Add a tenant device model library

## Why
Tenant users can select existing device models, but they cannot create or maintain the model records that drive device entry, shipping accessories, and rental statistics. Free-text model entry leaves devices without a canonical `model_id` and allows inconsistent names.

## What Changes
- Add a model-library subpage inside the device-management workspace.
- Support model creation, editing, activation, deactivation, and safe deletion.
- Show device usage counts and prevent deletion while a model is referenced.
- Require new and edited devices to select a canonical active model while preserving legacy devices for migration.
- Surface legacy free-text model groups and allow tenant administrators to assign all matching devices to a canonical model.

## Impact
- Affected specs: `device-model-library`
- Affected code: device-model APIs and service, device mutation validation, device-management view and tests
