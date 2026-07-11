# Change: Add Gantt Schedule Reordering

## Why

Future unshipped rentals are spread across devices of the same model, leaving avoidable schedule gaps. Operators need a safe one-click optimizer that preserves dates, fixed shipments, parent-child rentals, and manually confirmed relay arrangements. The existing rental slot lookup also returns online devices that are no longer lifecycle-active.

## What Changes

- Add a two-step Gantt workflow to confirm relay relationships, preview an OR-Tools schedule, and execute it.
- Reassign only eligible main rental `device_id` values within the same `model_id`.
- Persist confirmed relay relationships and keep relay chains on one device.
- Protect child rentals and all non-device rental fields with snapshot, lock, transaction, rollback, and audit checks.
- Restrict both schedule reordering and new-rental slot lookup to online, lifecycle-active devices.
- Add isolated automated tests that cannot connect to the production `192.*` database.
- Package OR-Tools in the existing amd64/arm64 Docker image.

## Impact

- Affected specs: `gantt-schedule-reordering`
- Affected backend: Gantt routes, handlers and services; device eligibility query; rental relay model and migration; audit logging
- Affected frontend: Gantt toolbar, two-step relay/preview dialog, Gantt store
- Affected deployment: Python requirements and multi-architecture Docker verification
- Affected tests: optimizer unit tests, API/service integration tests, frontend component/store tests, isolated MySQL transaction tests

## Safety

- No automated test may load the production `.env` or connect to a `192.*` database host.
- Preview performs no database writes.
- Execute changes only eligible main rental `device_id` fields and relay metadata in one transaction.
- Any snapshot, integrity, feasibility or database failure rolls back the entire execution.
