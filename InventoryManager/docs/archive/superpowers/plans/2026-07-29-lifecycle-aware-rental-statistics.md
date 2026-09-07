# Lifecycle-Aware Rental Statistics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Preserve each device's historical rental contribution through its lifecycle cutoff, prorate capacity and depreciation by day, and remove the obsolete online/offline device state.

**Architecture:** Add pure service-window helpers that model device service as `[first_order_date, lifecycle_date)` and use them from both periodic statistics and forecast calculations. Consolidate availability on `lifecycle_status`, migrate and drop the old `devices.status` column, then remove old status controls from backend and both Vue clients.

**Tech Stack:** Python 3, Flask, Flask-SQLAlchemy, Alembic, pytest, Vue 3, TypeScript, Vitest, Vite.

## Global Constraints

- `sold`, `decommissioned`, `damaged`, and `retired` use `lifecycle_date` as an exclusive service end.
- Existing `offline + active` devices migrate to `active` without creating a lifecycle date.
- Existing non-active lifecycle states and dates are never overwritten by the old status.
- Consignment devices remain permanently excluded; `2005`, `3005`, and `3006` stop being name-excluded.
- Main, non-cancelled rentals only; accessory rentals retain their existing behavior.
- Future forecasts use current `active` devices only.

---

### Task 1: Service-window calculations

**Files:**
- Create: `app/services/rental_statistics_service.py`
- Create: `tests/unit/test_rental_statistics_service.py`

**Interfaces:**
- Produces: `lifecycle_end_date(device) -> date | None`
- Produces: `service_overlap_days(first_order: date, service_end: date | None, period_start: date, period_end: date) -> int`
- Produces: `is_order_within_service(start_date: date, first_order: date, service_end: date | None) -> bool`
- Produces: `calculate_period_depreciation(purchase_price: float, purchase_date: date, period_start: date, period_end: date, service_end: date | None = None) -> float`

- [x] Write table-driven unit tests with literal expectations for full periods, mid-period cutoff, cutoff-day exclusion, active devices, pre-investment days, and missing lifecycle dates.
- [x] Run `pytest tests/unit/test_rental_statistics_service.py -q` and confirm failures are caused by missing helpers.
- [x] Implement the minimal pure helpers using half-open calendar intervals and the existing half-life depreciation formula.
- [x] Re-run the focused tests and confirm they pass.

### Task 2: Periodic statistics and forecast integration

**Files:**
- Modify: `app/routes/rental_stats_api.py`
- Create: `tests/integration/test_rental_stats_api.py`

**Interfaces:**
- Consumes Task 1 service-window helpers.
- Preserves: `GET /api/rental-stats/periodic`
- Preserves: `GET /api/rental-stats/x200u-forecast`
- Adds response field: `available_device_weeks: float`

- [x] Add integration fixtures for an active device and one device that exits mid-month, with orders before, on, and after the lifecycle date.
- [x] Assert the endpoint retains pre-exit order amount, excludes cutoff-day orders, reports literal prorated device-weeks, and stops depreciation at the cutoff.
- [x] Add forecast coverage proving exited-device history is retained while future device count excludes it.
- [x] Run the new integration tests and confirm the current global exclusion fails them.
- [x] Replace current lifecycle ID exclusion with permanent consignment exclusion only.
- [x] Build first-order and lifecycle-end maps for all owned devices, calculate daily capacity intersections, filter orders by service window, and clip depreciation.
- [x] Split forecast device sets into historical fleet and active future fleet, clipping historical depreciation and revenue per device end date.
- [x] Run the focused integration and helper tests until green.

### Task 3: Remove backend online/offline state

**Files:**
- Create: `migrations/versions/20260729_remove_device_online_status.py`
- Modify: `app/models/device.py`
- Modify: `app/services/device/device_service.py`
- Modify: `app/handlers/device_handlers.py`
- Modify: `app/routes/device_api.py`
- Modify: `app/routes/external_api.py`
- Modify: `app/services/rental_service.py`
- Modify: `app/services/inventory_service.py`
- Modify: `app/services/gantt/gantt_service.py`
- Modify: `app/services/gantt/reorder_service.py`
- Modify: `app/utils/scheduler_tasks.py`
- Modify: `app/routes/tracking_api.py`
- Delete: `app/services/device_status_service.py`
- Modify: affected backend tests and fixtures under `tests/`

**Interfaces:**
- `Device.is_in_service()` and `Device.in_service_query()` depend only on `lifecycle_status == "active"`.
- Device APIs expose lifecycle fields and reject obsolete `status` update/filter input with HTTP 400.
- External inventory statistics report lifecycle counts instead of online/offline counts.

- [x] Add failing model, API, availability, reorder, and migration tests proving active-only eligibility and obsolete-status rejection.
- [x] Run focused backend tests and confirm failures reference the old status behavior.
- [x] Add an Alembic migration that preserves lifecycle fields, treats old offline-active rows as active, drops `devices.status`, and recreates all-online status only on downgrade.
- [x] Remove the model column, old filters, serializers, mutation endpoints, status scheduler, and status route helpers.
- [x] Replace every device availability check with lifecycle-active checks; do not alter `Rental.status`.
- [x] Run `rg` to ensure no executable backend reference to `Device.status`, `device.status`, online/offline device values, or `DeviceStatusService` remains.
- [x] Run the backend test suite and fix only regressions caused by the consolidation.

### Task 4: Remove frontend online/offline controls

**Files:**
- Modify: `frontend/src/stores/gantt.ts`
- Modify: `frontend/src/components/GanttRow.vue`
- Modify: `frontend/src/components/GanttChart.vue`
- Modify: affected files under `frontend/tests/`
- Modify: `frontend-mobile/src/stores/gantt.ts`
- Modify: `frontend-mobile/src/views/DeviceStatusView.vue`
- Modify: `frontend-mobile/src/views/EditRentalView.vue`
- Modify: affected files under `frontend-mobile/e2e/`
- Regenerate: `static/vue-dist/`
- Regenerate: `static/vue-mobile-dist/`

**Interfaces:**
- Device TypeScript types contain `lifecycle_status` but no device `status`.
- Available-device computed values require `lifecycle_status === "active"`.
- Device status screens edit lifecycle status only.

- [x] Update frontend unit fixtures first so type-checking exposes every obsolete device-status dependency.
- [x] Remove PC device status classes, emits, handlers, store action, and default field.
- [x] Convert mobile status view tabs and actions to lifecycle-only behavior; filter editable rental devices by active lifecycle.
- [x] Run PC unit tests and both TypeScript checks.
- [x] Build PC and mobile bundles into the Flask static directories.
- [x] Search source and generated bundles for user-visible online/offline device controls and remove remaining occurrences.

### Task 5: Full verification, documentation alignment, and publish

**Files:**
- Modify: `docs/superpowers/specs/2026-07-29-lifecycle-aware-rental-statistics-design.md` only if implementation discovers a necessary factual correction.
- Modify: this plan to check completed tasks.

- [x] Run `pytest -q`.
- [x] Run `npm run test:run` and `npm run build` in `frontend/`.
- [x] Run `npm run build` in `frontend-mobile/`.
- [x] Run `git diff --check` and inspect the complete diff for accidental rental-status changes or user-owned files.
- [x] Confirm `rg` finds no executable device online/offline logic while ordinary rental `status` logic remains.
- [x] Mark plan tasks complete, stage only related files, commit with a focused message, and run a final clean verification.
- [x] Push the current branch and report the pushed commit.
