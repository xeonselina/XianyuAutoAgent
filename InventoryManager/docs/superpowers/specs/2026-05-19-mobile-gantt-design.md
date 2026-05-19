# Mobile Gantt — Design Spec

**Date:** 2026-05-19  
**Status:** Approved  
**Scope:** iPhone-only mobile frontend for the InventoryManager rental Gantt system. Two main views: Gantt chart and batch shipping. Implemented as a completely separate Vue 3 app — no changes to the existing PC frontend.

---

## 1. Overall Architecture

### App Structure

A standalone Vue 3 + TypeScript + Vite app in `frontend-mobile/` alongside the existing `frontend/`.

```
InventoryManager/
├── frontend/              # existing PC app (unchanged)
├── frontend-mobile/       # new mobile-only app
│   ├── src/
│   │   ├── main.ts
│   │   ├── App.vue
│   │   ├── router/
│   │   │   └── index.ts   # Vue Router 4
│   │   ├── stores/
│   │   │   └── gantt.ts   # copied from frontend/src/stores/gantt.ts (kept in sync manually)
│   │   ├── views/
│   │   │   ├── GanttView.vue
│   │   │   ├── BatchShippingView.vue
│   │   │   ├── CreateRentalView.vue
│   │   │   └── EditRentalView.vue
│   │   └── components/
│   │       ├── GanttGrid.vue
│   │       ├── RentalBottomSheet.vue
│   │       └── BatchShippingCard.vue
│   ├── vite.config.ts
│   ├── package.json
│   └── index.html
└── static/
    ├── vue-dist/          # PC app build output (unchanged)
    └── vue-mobile-dist/   # mobile app build output
```

### Tech Stack

| Layer | Choice |
|---|---|
| Framework | Vue 3 + TypeScript |
| Build | Vite |
| UI Library | Vant 4 |
| State | Pinia (reuse `gantt.ts` store from PC app verbatim) |
| Router | Vue Router 4 |
| HTTP | Same `axios` calls to Flask backend — no API changes |
| E2E | Playwright, iPhone 14 viewport (390×844) |

### Flask Serving

- `GET /mobile` → serves `static/vue-mobile-dist/index.html`
- All existing API routes remain unchanged
- `vite.config.ts` sets `base: '/mobile/'` and `outDir: '../static/vue-mobile-dist'`

---

## 2. Navigation

Bottom tab bar (Vant `Tabbar`), 2 tabs:

| Tab | Icon | Route |
|---|---|---|
| 甘特图 | calendar-o | `/mobile/gantt` |
| 批量发货 | logistics | `/mobile/batch-shipping` |

Full-screen overlay pages (no tab bar):

| Page | Route | Entry point |
|---|---|---|
| 新建租赁 | `/mobile/create-rental` | `+` button in Gantt nav bar |
| 编辑租赁 | `/mobile/edit-rental/:id` | 编辑 button in bottom sheet |

---

## 3. Gantt Chart View

### Layout

```
┌─────────────────────────────────┐
│ [甘特图]        [日期范围] [+新建]│  ← nav bar
├──────────┬──────────────────────┤
│  设备     │ 1  2  3  ...  14   │  ← date header (fixed 14 cols)
├──────────┼──────────────────────┤
│ iPhone15P│ ████ · · ════       │  ← row 26px height
│ iPhone14 │ · · ████ · ·       │
│ iPad Pro │ ════ ████ · ·       │
│ ...      │ · · · · ████       │
└──────────┴──────────────────────┘
         (scrollable vertically)
```

### Date Grid

- **Fixed 14-day window** — all 14 days visible simultaneously, no horizontal scroll.
- Day columns are equal-width: `(100% − device-column-width) / 14`.
- Device column: fixed `54px` wide.
- Default window: today − 2 days through today + 11 days (keeps "today" visible near left side).
- User can shift the window forward/backward with `<` `>` arrow buttons in the nav bar (shifts by 7 days).

### Row Design

- Row height: **26px** (single-line device name only — no serial number).
- Device column: device name, `font-size: 7px`, single line, `overflow: hidden; white-space: nowrap`.
- Two horizontal bars per row (if logistics data exists):
  - **Upper bar** (rental period): `top: 3px`, `height: 9px`, color `#409eff`, text = customer name.
  - **Lower bar** (logistics window): `top: 14px`, `height: 7px`, color `#a0cfff`, text = "物流". Only rendered when both `ship_out_time` and `ship_in_time` are populated.
- Rows are sorted by device name.
- Rows scroll vertically when device list exceeds viewport height.

### Bottom Sheet (租赁详情)

Triggered by tapping any rental bar. Uses Vant `Popup` position `bottom` with round corners.

Content:
```
────────────────────
  ──── (drag handle)

  iPhone 15 Pro
  ┌──────────────────────────┐
  │ 租客     张三            │
  │ 发货日   2026-05-18      │
  │ 起租日   2026-05-19      │
  │ 还租日   2026-05-22      │
  │ 入库日   2026-05-24      │
  │ 地址     上海市浦东...   │
  │ 运单号   SF1234567890    │
  │ 状态     已发货          │
  └──────────────────────────┘
  [ 编辑 ]  [ 删除 ]
────────────────────
```

Fields shown:
- 租客 (`customer_name`)
- 发货日 (`ship_out_time` — date portion only, "—" if null)
- 起租日 (`start_date`)
- 还租日 (`end_date`)
- 入库日 (`ship_in_time` — date portion only, "—" if null)
- 地址 (`destination`, truncated to 2 lines)
- 运单号 (`ship_out_tracking_no`, "—" if null)
- 状态 (localized status badge)

Buttons:
- **编辑** → navigate to `/mobile/edit-rental/:id`
- **删除** → Vant Dialog confirm → call `ganttStore.deleteRental(id)` → close sheet and refresh

Dismiss: swipe down or tap outside.

### Create Rental Entry

`+` button in the Gantt nav bar (top-right). Navigates to `/mobile/create-rental`.

---

## 4. Batch Shipping View

### Layout

```
┌─────────────────────────────────┐
│ [批量发货]                [筛选] │  ← nav bar
├─────────────────────────────────┤
│  5/19  至  5/20    [查询]       │  ← date range filter
│  共 3 单                  [全选] │  ← stats bar
├─────────────────────────────────┤
│ ☑  iPhone 15 Pro · 张三  待发货 │
│    📅 5/19  📍 上海浦东新区...  │
│    📦 —                         │  ← card 1
├─────────────────────────────────┤
│ □  MacBook Pro · 李四   预约中  │
│    📅 5/19  📍 北京朝阳区...    │
│    📦 SF9876543210              │  ← card 2
├─────────────────────────────────┤
│ ...  (scrollable)               │
├─────────────────────────────────┤
│ [ 预约发货 (1) ] [ 打印面单 (1) ]│  ← fixed bottom action bar
└─────────────────────────────────┘
```

### Data Source

Cards are rentals with a `ship_out_time` that falls within the selected date range. Fetched via `GET /api/rentals/by-ship-date` with `start_date` and `end_date` query params (same endpoint the PC batch shipping view uses). Results are sorted by `ship_out_time` ascending.

### Cards

Each card (Vant `Cell` or custom div) shows:
- Checkbox (Vant `Checkbox`) on the left
- Device name + customer name + status badge
- Ship date, destination (truncated)
- Tracking number (or "—")

Already-shipped orders are shown with muted text and their checkbox disabled.

### Bottom Action Bar

Fixed at the bottom of the viewport. Only visible when ≥1 card is checked.

- **预约发货 (N)** — calls `POST /api/shipping-batch/schedule` with array of selected rental IDs
- **打印面单 (N)** — calls `POST /api/shipping-batch/print-waybills` with array of selected rental IDs

### Filters

- Default date range: today → today + 1 day
- "筛选" button: opens Vant ActionSheet or overlay for status filter (待发货 / 已预约 / 全部)

---

## 5. Create Rental Form (`/mobile/create-rental`)

Full-screen page with Vant form components. Navigation: back arrow returns to Gantt.

### Form Fields

| Field | Component | Notes |
|---|---|---|
| 闲鱼订单号 | `van-field` + fetch button | Triggers order info auto-fill |
| 设备型号 | `van-picker` | Dropdown of device models |
| 可用设备 | `van-picker` | Populated after availability check; shows available device slots |
| 起租日 | `van-date-picker` | Triggers availability check when changed |
| 还租日 | `van-date-picker` | Must be ≥ start date; triggers availability check |
| 物流天数 | `van-stepper` | Default 1, range 0–7; affects ship time auto-calc |
| 发货时间 | read-only display | Auto-calculated: `start_date − (1 + logisticsDays) days` |
| 入库时间 | read-only display | Auto-calculated: `end_date + (1 + logisticsDays) days` |
| 客户姓名 | `van-field` | Auto-filled from order fetch |
| 客户电话 | `van-field` | Auto-filled from order fetch or extracted from destination |
| 收货地址 | `van-field` (textarea) | Auto-filled from order fetch; watching triggers phone extraction |
| 订单金额 | `van-field` | Auto-filled from order fetch |
| 买家ID | `van-field` | Auto-filled from order fetch |
| 随机配件 | `van-checkbox-group` | handle (手柄) + lens_mount (镜头座) |
| 手机支架 | `van-picker` | From accessories inventory |
| 三脚架 | `van-picker` | From accessories inventory |
| 照片转移 | `van-switch` | Photo transfer included |

### Frontend Logic Preserved

**Xianyu order auto-fill** (`handleFetchOrderInfo`):
- POST `/api/rentals/fetch-xianyu-order` with order number
- On success: fill `customerName`, `customerPhone`, `destination` (name+phone+address combined), `buyerId`, `orderAmount`

**Phone auto-extraction** (watcher on `destination`):
- When `destination` changes and `customerPhone` is empty: extract 11-digit mobile number from the destination text and populate `customerPhone`

**Logistics days → ship time auto-calc** (computed properties):
- `shipOutTime = startDate − (1 + logisticsDays) days`
- `shipInTime = endDate + (1 + logisticsDays) days`
- Re-computed whenever `startDate`, `endDate`, or `logisticsDays` changes

**Device availability check** (triggered when start + end dates are set):
- Calls `ganttStore.findAvailableSlot(start, end, logisticsDays, modelId, false)`
- Populates the "可用设备" picker with available slots
- Shows "无可用设备" if none found

**Duplicate rental check** (before submit):
- `conflictDetection.checkDuplicateRental()` with customer + destination
- Shows Vant Dialog warning if duplicate found; user can cancel or proceed

**Submit** builds `rentalData` with all fields including auto-calculated ship times, calls `ganttStore.createRental(rentalData)`, then navigates back to Gantt.

---

## 6. Edit Rental Form (`/mobile/edit-rental/:id`)

Full-screen page. Entry: "编辑" button in bottom sheet. Navigation: back arrow returns to Gantt (preserves scroll position via Vue Router scroll behavior).

### Form Fields

| Field | Component | Notes |
|---|---|---|
| 起租日 | read-only display | **NOT editable** |
| 还租日 | `van-date-picker` | Min = `start_date` |
| 设备 | `van-picker` | Change triggers conflict check |
| 客户电话 | `van-field` | |
| 收货地址 | `van-field` (textarea) | Watching triggers phone extraction |
| 发货单号 | `van-field` + query button | Disabled if empty; query → tracking status |
| 入库单号 | `van-field` + query button | Disabled if empty |
| 发货时间 | `van-date-time-picker` | Date + hour:minute, no seconds |
| 入库时间 | `van-date-time-picker` | Date + hour:minute, no seconds |
| 订单状态 | `van-picker` | not_shipped / scheduled_for_shipping / shipped / returned / completed / cancelled |
| 随机配件 | `van-checkbox-group` | handle + lens_mount |
| 手机支架 | `van-picker` | |
| 三脚架 | `van-picker` | |

(Fields not in the edit scope — `start_date`, `customerName`, `buyerId`, `orderAmount` — are shown read-only for reference but not submitted.)

### Frontend Logic Preserved

**`initForm()`**: On page load, fetches latest rental data via `ganttStore.getRentalById(id)`, maps API format to UI state (includes_handle/lens_mount → `bundledAccessories` checkboxes, accessories array → `phoneHolderId`/`tripodId`).

**Device conflict check** (when device selection changes):
- `conflictDetection.checkDeviceConflict(newDeviceId, rentalId)` async check
- If conflict found: show Vant Dialog confirm — user must acknowledge to proceed

**Phone auto-extraction** (watcher on `destination`):
- Same logic as create form — extract phone when `customerPhone` is empty

**Submit**: PATCH `/api/rentals/:id` with fields: `device_id`, `end_date`, `customer_phone`, `destination`, `ship_out_tracking_no`, `ship_in_tracking_no`, `ship_out_time`, `ship_in_time`, `status`, `includes_handle`, `includes_lens_mount`, accessories array. Navigate back on success.

---

## 7. E2E Tests

Test runner: Playwright. Viewport: iPhone 14, `390 × 844`. Tests live in `frontend-mobile/e2e/`.

### `gantt.spec.ts`

| Test case | Steps | Validates |
|---|---|---|
| Load gantt view | Navigate to `/mobile`; wait for gantt grid | 14-day header visible |
| Vertical list scroll | Scroll gantt list down, then back up | Rows below viewport are reachable; scroll position updates |
| Tap rental bar → bottom sheet | Tap a rental bar | Bottom sheet appears with all 4 date fields |
| Bottom sheet dismiss | Swipe down on sheet | Sheet closes |
| Navigate to create rental | Tap `+` button | Create rental page renders |

### `batch-shipping.spec.ts`

| Test case | Steps | Validates |
|---|---|---|
| Load batch shipping view | Tap batch-shipping tab | Card list renders |
| Date filter query | Set date range, tap 查询 | Cards matching date range shown |
| Vertical list scroll | Scroll card list down, then back up | Cards below viewport reachable; scroll position updates |
| Select card | Tap checkbox on a card | Bottom action bar appears; count badge = 1 |
| Select all | Tap 全选 | All cards checked; count badge = total |
| Deselect | Tap checked card | Count decrements; bar hides when count = 0 |

---

## 8. Non-Goals

- No responsive/adaptive changes to the existing PC frontend (`frontend/`)
- No changes to Flask backend routes or data models
- No PWA / service workers
- No push notifications
- No print functionality beyond the batch shipping waybill button (server-side)
- iOS App Store / native app — this is a mobile web app only
