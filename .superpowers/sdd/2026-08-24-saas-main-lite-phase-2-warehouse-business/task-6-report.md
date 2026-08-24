# Task 6 implementer report

## Result

- Implemented the warehouse-aware tenant interface on top of Task 1-5 without
  adding a table, migration, UI framework, generic request layer, persisted
  warehouse preference, token storage, or background workflow.
- Added exactly one backend surface: authenticated `GET /api/warehouses`.
  Active Admin and Operator members receive only public Warehouse fields plus
  SF/Kuaimai configured booleans. Existing `/api/settings/*` Admin guards,
  tenant binding, and CSRF handling are unchanged.
- Commit message: `feat: add warehouse-aware tenant interface`.

## Implemented behavior

### Tenant and warehouse navigation

- Desktop and mobile each use a Pinia store whose Warehouse list and current
  selection exist only in memory. One Warehouse selects automatically without
  another control; multiple Warehouses initially select the first and allow
  the read-only `all` selection.
- The desktop header shows tenant, current Warehouse, role, Admin-only settings,
  and logout. The mobile header shows tenant, current Warehouse, and role, with
  no settings or credential UI.
- Device, inventory, Gantt, Rental batch/search, pending-return, daily-stat, and
  supported rental-stat reads now send `warehouse_id` explicitly. Gantt,
  Booking, mobile create/edit, and rental statistics reload after selection
  changes where live refresh is needed.
- Device/Rental/slot/reorder writes require a concrete numeric Warehouse in the
  frontend. `all` is never sent as a write Warehouse.

### Settings

- Replaced the Phase 1 settings shell with member, Warehouse, and Xianyu tabs.
  The Xianyu tab remains the approved “下一阶段配置” empty state.
- Members can be added by phone and role, have their role changed, and be
  disabled/re-enabled through the existing Admin-only API.
- Warehouse editing uses one drawer with basic information, SF, and
  Kuaimai/printer sections. It supports default names, province/city, SF
  partner/monthly account/checkword/test mode/sender fields, and Kuaimai app
  plus printer SN.
- Secret inputs always open blank. Blank values preserve the existing secret;
  responses and UI use configured booleans and never expose ciphertext.

### Movement and receipt repair

- Normal Device movement selects a target Warehouse, previews automatic,
  shortage, manual, and blocked impacts, then executes the returned token. A
  stale normal token triggers exactly one automatic re-preview and retry.
- Inspection defaults the receiving Warehouse to the Rental Warehouse, lets the
  operator select actual received Device attachments, and submits both fields.
- Inspection consumes Task 5's returned aggregate `warehouse_impacts` token and
  executes it directly through `/move`; it never requests a normal preview for
  Devices that have already entered the receiving Warehouse.

## Strict TDD evidence

- Backend RED: the public Warehouse endpoint returned 404 before the route was
  added. Final focused coverage proves Admin and Operator access, exact public
  output/redaction, unauthenticated rejection, and unchanged Operator rejection
  for every settings endpoint.
- Initial frontend RED: warehouse navigation, settings API, movement dialog,
  inspection receipt repair, explicit business Warehouse requests, and the
  mobile memory store failed on missing modules or missing request fields before
  implementation.
- Rental-stat audit RED: the existing periodic/forecast page omitted
  `warehouse_id` and did not reload on selection change. The added behavior test
  failed on the old URLs before the minimal page change.
- Full-suite compatibility RED: five legacy BookingDialog tests had no Warehouse
  fixture and were correctly blocked by the new `all` write guard. Their test
  setup now creates one explicit Warehouse; production validation was not
  weakened.

## Verification

- Backend full suite against isolated MariaDB 10.11 and the isolated
  provisioner: `489 passed`, 67 pre-existing SQLAlchemy `Query.get()` warnings,
  in 144.35 seconds.
- Backend focused settings/public Warehouse suite: `2 passed, 31 deselected`.
  Task 2-5/auth/tenant-boundary regression run: `151 passed`, 35 warnings.
- Desktop full Vitest: `37 files`, `371 passed`.
- Desktop `vue-tsc --build`: passed.
- Desktop production Vite build: passed and rebuilt `static/vue-dist`.
- Mobile `vue-tsc --noEmit` plus production Vite build: passed and rebuilt
  `static/vue-mobile-dist`.
- `git diff --check`: clean. Source/generated scan found no local/session
  storage, embedded master key, test database credential, or ciphertext field
  in either frontend or built static output.
- MariaDB cleanup audit: the three fixed schemas contain zero tables; no dynamic
  provisioning database/user, temporary test user, or temporary host-specific
  root account remains.

## Size

- Handwritten production code: **1,333 additions / 74 deletions, net +1,259**.
- Handwritten tests: **578 additions / 8 deletions, net +570**.
- Generated component/static output: **218 additions / 213 deletions, net +5**.
- This report is counted separately as documentation. The production growth is
  concentrated in the two small in-memory stores, the two settings forms, one
  movement dialog, one header, and direct edits to existing screens; there is
  no generalized frontend architecture or duplicated backend business layer.

## Residual notes

- The desktop build retains the existing large-chunk warning, and the existing
  RentalContract template retains its invalid direct `tr`-under-`table` Vite
  warnings. Neither warning was introduced by Task 6.
- Xianyu shop configuration intentionally remains empty until Phase 3, as
  required by the Phase 2 boundary.
