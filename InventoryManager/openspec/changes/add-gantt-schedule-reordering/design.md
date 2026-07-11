# Design: Gantt Schedule Reordering

## Context

The Gantt chart stores a main device rental and optional accessory child rentals. Logistics occupancy is represented by `ship_out_time` through `ship_in_time`. Existing overlapping rentals can represent intentional customer-to-customer relay shipments. Reordering must therefore optimize device assignments without changing dates or breaking order composition.

The detailed approved design is recorded in `docs/superpowers/specs/2026-07-11-gantt-schedule-reordering-design.md`.

## Goals / Non-Goals

**Goals:**

- Optimize future `not_shipped` main rentals independently per `model_id` with OR-Tools CP-SAT.
- Require relay review and a no-write preview before execution.
- Preserve every parent and child rental and all non-device fields.
- Persist relay chains and constrain them to one main device.
- Use only online, lifecycle-active target devices.
- Execute atomically with snapshot and row-lock protection.

**Non-Goals:**

- Moving child rentals or accessory devices.
- Changing rental or logistics dates.
- Moving scheduled, shipped, or in-progress rentals.
- Running tests against production data by default.

## Decisions

### Two-step workflow

Step one requires a decision for every pre-existing overlap longer than the allowed same-day turnaround. Step two shows model summaries and per-rental customer, phone, address, date and device changes, then executes directly.

### Relay persistence

A new non-branching predecessor/successor relation persists confirmed relays. Relay chains become indivisible logical blocks in the solver. A chain containing a fixed rental is fixed to its current device.

### Solver model

Each model is solved independently. Normal and relay blocks use optional intervals per eligible device, exactly-one assignment, fixed anchors and `NoOverlap`. Objectives are lexicographic: minimize used devices, then idle gaps, then changed assignments. Each model has a three-second limit, one worker and a fixed random seed.

### Safe execution

The signed ten-minute preview token carries a snapshot hash, relay choices and server-generated assignment. Execute locks all related rows, rebuilds the snapshot, pins the preview assignment into a feasibility model, validates invariants, and writes device changes, relay metadata and audit rows in one transaction.

### Device eligibility

Both the slot finder and reorder candidate query use the same predicate: non-accessory where appropriate, `status = online`, and `lifecycle_status = active`.

### Test isolation

Tests require explicit `TEST_DATABASE_URL`, `TESTING=true`, a database name containing `test`, and a non-`192.*` host. MySQL-specific tests use an isolated container; production dumps are opt-in, read-only and anonymized.

## Risks / Trade-offs

- OR-Tools adds approximately 232 MB installed image size. The existing multi-stage multi-architecture Docker build contains the dependency, so the NAS host needs no package installation.
- A three-second limit may return a feasible but unproven result. The UI labels solver status, and only fully feasible assignments can execute.
- Row locking can briefly serialize concurrent rental edits. The operation is bounded and rejects stale previews rather than overwriting changes.
- Existing invalid relay metadata can block one model. The UI identifies the records for manual correction while leaving all rental data unchanged.

## Migration Plan

1. Add the relay binding table and constraints.
2. Deploy backend support while leaving the feature button unavailable until APIs pass health checks.
3. Deploy the two-step frontend.
4. Verify OR-Tools import on both image architectures.
5. Roll back by hiding the frontend action and reverting application code; the additive relay table can remain without affecting existing rentals.
