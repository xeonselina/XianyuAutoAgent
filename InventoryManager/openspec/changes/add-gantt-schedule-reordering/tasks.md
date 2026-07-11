## 1. Test Isolation and Device Eligibility

- [ ] 1.1 Add guarded test database configuration that rejects `192.*` hosts and non-test database names.
- [ ] 1.2 Add failing tests for lifecycle-inactive devices in rental slot lookup.
- [ ] 1.3 Centralize the online-and-active device eligibility predicate and fix slot lookup.

## 2. Relay Binding Domain

- [ ] 2.1 Add relay binding model, migration and non-branching database constraints.
- [ ] 2.2 Add validation and tests for main-rental, same-model, same-device, chronological relay chains.
- [ ] 2.3 Add overlap analysis service and API tests.

## 3. OR-Tools Preview

- [ ] 3.1 Add the pinned OR-Tools production dependency and Docker import smoke checks.
- [ ] 3.2 Add pure optimizer tests for eligibility, same-model isolation, same-day turnaround, fixed anchors, relay chains, objectives, timeout and infeasibility.
- [ ] 3.3 Implement logical block construction and per-model CP-SAT optimization.
- [ ] 3.4 Implement signed snapshot tokens and the no-write preview API.

## 4. Atomic Execution

- [ ] 4.1 Add failing MySQL integration tests for row locking, stale snapshots, rollback and replay.
- [ ] 4.2 Implement locked snapshot rebuild and pinned-assignment feasibility validation.
- [ ] 4.3 Implement one-transaction relay, main rental device and audit updates.
- [ ] 4.4 Implement pre-commit parent-child and rental-set invariant checks.

## 5. Gantt User Interface

- [ ] 5.1 Add store APIs and tests for analyze, preview and execute.
- [ ] 5.2 Add the Gantt toolbar action and relay confirmation step with customer contact details.
- [ ] 5.3 Add the preview step with model summaries, detailed changes, return action and direct execute button.
- [ ] 5.4 Add stale, expired, infeasible, skipped and rollback error states.

## 6. Verification

- [ ] 6.1 Run backend unit and isolated MySQL integration suites.
- [ ] 6.2 Run frontend unit and integration suites.
- [ ] 6.3 Build amd64 and arm64 images and verify CP-SAT import.
- [ ] 6.4 Confirm only eligible main rental `device_id` fields change in end-to-end fixtures.
