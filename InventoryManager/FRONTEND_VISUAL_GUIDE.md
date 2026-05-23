# InventoryManager Frontend - Visual Summary

## Architecture Overview

```
InventoryManager/
│
├── /frontend                    [DESKTOP APP]
│   ├── src/
│   │   ├── views/               (12 page components)
│   │   ├── components/          (40 reusable components)
│   │   ├── stores/              (Pinia stores)
│   │   ├── router/              (11 routes)
│   │   ├── utils/               (Helpers)
│   │   └── App.vue + main.ts
│   ├── package.json             (Element Plus, ECharts, Vue 3)
│   └── vite.config.ts
│
├── /frontend-mobile             [MOBILE APP]
│   ├── src/
│   │   ├── views/               (4 page components)
│   │   ├── components/          (4 main components)
│   │   ├── stores/              (Pinia stores)
│   │   ├── router/              (4 routes)
│   │   ├── utils/               (Helpers)
│   │   └── App.vue + main.ts
│   ├── package.json             (Vant, Vue 3)
│   └── vite.config.ts
│
└── /static                      [BUILT OUTPUT]
    ├── vue-dist/                (Desktop build)
    └── mobile-dist/             (Mobile build)
```

---

## Desktop App Component Hierarchy

```
App.vue
└── RouterView
    ├── GanttView (main page)
    │   └── GanttChart
    │       ├── toolbar (buttons, date picker)
    │       ├── filters (search, status)
    │       └── GanttRow (×N)
    │           ├── device name
    │           ├── rental bars
    │           └── RentalTooltip (on hover)
    │
    ├── BatchShippingView
    │   ├── filter controls
    │   ├── shipping list
    │   └── batch actions
    │
    ├── StatisticsView
    │   └── ECharts visualizations
    │
    ├── InspectionView
    │   └── ChecklistForm
    │
    ├── RentalContractView
    │   └── printable contract
    │
    └── ... (7 more views)
```

---

## Mobile App Component Hierarchy

```
App.vue
├── RouterView (with keep-alive)
│   ├── GanttView
│   │   ├── van-nav-bar
│   │   │   ├── date nav buttons
│   │   │   └── create button
│   │   ├── GanttGrid (14-day calendar)
│   │   │   ├── header row (dates)
│   │   │   └── device rows (×N)
│   │   │       └── rental bars (×M)
│   │   └── RentalBottomSheet (modal)
│   │       ├── rental info grid
│   │       └── action buttons
│   │
│   ├── BatchShippingView
│   │   ├── van-nav-bar
│   │   ├── van-checkbox-group (items)
│   │   └── BatchShippingCard (×N)
│   │
│   ├── CreateRentalView
│   │   ├── van-nav-bar (back)
│   │   └── van-form
│   │       ├── order info section
│   │       ├── rental dates section
│   │       ├── accessories section
│   │       ├── shipping info section
│   │       └── submit button
│   │
│   └── EditRentalView
│       └── (similar to CreateRentalView)
│
└── van-tabbar (footer - conditional)
    ├── 甘特图 (Gantt)
    └── 批量发货 (Batch Shipping)
```

---

## State Management (Pinia Store)

```
stores/gantt.ts
│
├── State
│   ├── devices: Device[]
│   ├── rentals: Rental[]
│   ├── currentDate: Date
│   ├── selectedDate: Date | null
│   ├── loading: boolean
│   └── error: string | null
│
├── Actions (methods)
│   ├── loadData()               GET /api/gantt/data
│   ├── createRental(data)       POST /api/rentals
│   ├── updateRental(id, data)   PUT /api/rentals/:id
│   ├── deleteRental(id)         DELETE /api/rentals/:id
│   ├── navigateWeek(direction)  Shift date window
│   └── goToToday()              Jump to today
│
├── Getters (computed)
│   ├── dateRange
│   ├── currentPeriod
│   ├── availableDevices
│   └── getRentalsForDevice(id)
│
└── Shared between
    ├── Desktop (frontend/src/stores/gantt.ts)
    └── Mobile (frontend-mobile/src/stores/gantt.ts)
```

---

## Data Model - Key Interfaces

```typescript
// Device - Equipment being rented out
Device {
  id: number
  name: string              // Equipment model name
  serial_number: string
  model: string
  status: 'online' | 'offline'
  lifecycle_status: 'active' | 'sold' | 'decommissioned' | 'damaged'
  is_accessory: boolean
}

// Rental - A rental transaction
Rental {
  id: number
  device_id: number
  device: Device?            // Populated on load
  
  // Customer info
  customer_name: string
  customer_phone: string
  destination: string        // Shipping address
  
  // Rental period
  start_date: string         // YYYY-MM-DD (when customer gets it)
  end_date: string           // YYYY-MM-DD (when customer returns it)
  
  // Shipping period
  ship_out_time?: string     // When we send it out
  ship_in_time?: string      // When we receive it back
  ship_out_tracking_no?: string
  ship_in_tracking_no?: string
  
  // Status tracking
  status: string             // not_shipped | shipped | returned | completed | cancelled
  
  // Accessories
  accessories: Accessory[]
  includes_handle: boolean
  includes_lens_mount: boolean
  
  // Order info
  xianyu_order_no?: string   // Marketplace order ID
  order_amount?: number
  buyer_id?: string
  photo_transfer: boolean    // Photo transfer service flag
}
```

---

## Calendar Visualization Logic

### DESKTOP (GanttChart.vue)
```
Timeline: ←[30 days]→
          [Today-15] ... [Today] ... [Today+15]

Display:
┌─────────────────────────────────────────────────────┐
│ Device Name  │ Day1  │ Day2  │ Day3  │ ... │ Day30 │
├─────────────────────────────────────────────────────┤
│ Device A     │ [■■■  ├─────→ Rental A               │
│              │       ├─ ■■■ ┤ Logistics             │
│ Device B     │       │ [■■■■■■] Rental B           │
│ Device C     │ [■ ├─ ■ ├─ ■] Multiple rentals     │
└─────────────────────────────────────────────────────┘

Features:
- Drag-drop to reschedule
- Hover for tooltip
- Color-coded by status
- Full month view
```

### MOBILE (GanttGrid.vue)
```
Timeline: ←[14 days]→ (sliding window)
          Arrows to shift by 7 days

Display:
┌──────────────────────────────────────────────┐
│ Dev │ 5/1  │ 5/2  │ 5/3  │ ... │ 5/14       │
├──────────────────────────────────────────────┤
│ A   │ [■   │      │ [■   │ ... │           │
│     │  ■   │      │  ■   │     │           │
│ B   │      │ [■■■ ├──→ │      │           │
│     │      │  ■■  │     │      │           │
│ C   │      │      │      │     │ [■        │
│     │      │      │      │     │  ■        │
└──────────────────────────────────────────────┘
    ◄─── Upper bar: Rental period (blue)
    ◄─── Lower bar: Logistics period (light blue)

Features:
- Tap rental bar → bottom sheet
- Touch scrolling
- Week navigation
- Very compact (mobile-optimized)
```

---

## Mobile UI Component Details

### GanttGrid.vue - Grid Layout
```
Header (sticky, height: 36px)
├── Device column (54px) | Date columns (×14, flex)
│   [设备] | [5/1] | [5/2] | ... | [5/14]
│   [  ]  | [日] | [一] | ... | [六]
│
Body (scrollable)
├── Row 1 (Device A, height: 26px)
│   ├── Device col | 14 date cells
│   └── Overlay rental bars
│       ├── Upper bar (#409eff): start_date→end_date
│       └── Lower bar (#a0cfff): ship_out_time→ship_in_time
├── Row 2 (Device B)
│   └── ...
└── Row N
```

### RentalBottomSheet.vue - Modal
```
┌────────────────────────────────┐
│ ─── Drag handle ─── (4px line) │
├────────────────────────────────┤
│   Device Name (centered title) │
├────────────────────────────────┤
│ 租客      │ Customer Name     │
│ 发货日    │ Ship Date         │
│ 起租日    │ Start Date        │
│ 还租日    │ End Date          │
│ 入库日    │ Return Date       │
│ 地址      │ Address (wrap)    │
│ 运单号    │ Tracking Number   │
│ 状态      │ [Status Tag]      │
├────────────────────────────────┤
│ [  编辑  ] [  删除  ]          │
└────────────────────────────────┘
        (gap: 12px between)
```

### CreateRentalView.vue - Form Sections
```
┌─────────────────────────────────────┐
│ ←  新建租赁                         │  (navbar)
├─────────────────────────────────────┤
│ 订单信息                            │  (section title)
│ ┌─────────────────────────────────┐ │
│ │ 闲鱼订单号 │ [input] [拉取]      │ │
│ │ 客户姓名 * │ [input]             │ │
│ │ 客户电话   │ [input tel]         │ │
│ │ 收货地址   │ [textarea]          │ │
│ │ 订单金额   │ [number]            │ │
│ │ 买家ID     │ [input]             │ │
│ └─────────────────────────────────┘ │
│                                     │
│ 租赁日期                            │
│ ┌─────────────────────────────────┐ │
│ │ 设备型号 * │ [picker]            │ │
│ │ 起租日 *   │ [date picker]       │ │
│ │ 还租日 *   │ [date picker]       │ │
│ └─────────────────────────────────┘ │
│                                     │
│ 配套附件                            │
│ ┌─────────────────────────────────┐ │
│ │ ☑ 包含手柄 (Accessory 1)        │ │
│ │ ☐ 包含镜头座 (Accessory 2)      │ │
│ │ ☑ 代传照片                      │ │
│ └─────────────────────────────────┘ │
│                                     │
│ 发货信息                            │
│ ┌─────────────────────────────────┐ │
│ │ 发货日期   │ [date picker]       │ │
│ │ 发货时间   │ [time picker]       │ │
│ │ 收货日期   │ [date picker]       │ │
│ │ 收货时间   │ [time picker]       │ │
│ │ 发货单号   │ [input]             │ │
│ │ 收货单号   │ [input]             │ │
│ └─────────────────────────────────┘ │
│                                     │
│            [  提交  ]               │
└─────────────────────────────────────┘
```

---

## Navigation Flow

### Desktop (Element Plus routing)
```
/ (home)
├─ GanttView (main calendar)
├─ BatchShippingView (batch shipping)
├─ BatchShippingOrderView (batch detail)
├─ RentalContractView (/contract/:id)
├─ ShippingOrderView (/shipping/:id)
├─ StatisticsView (dashboard)
├─ RentalStatsView (analytics)
├─ SFTrackingView (tracking)
├─ InspectionView (inspection)
├─ InspectionRecordsView (inspection history)
└─ AboutView (about)
```

### Mobile (Vant routing)
```
/mobile/
├─ /gantt (GanttView) + tabbar
│  └─ /create-rental (CreateRentalView) - no tabbar
│  └─ /edit-rental/:id (EditRentalView) - no tabbar
│
├─ /batch-shipping (BatchShippingView) + tabbar
│
└─ [Tabbar navigation]
   ├─ 甘特图 → /gantt
   └─ 批量发货 → /batch-shipping
```

---

## Key Features by Component

### GanttGrid.vue (Mobile Calendar)
✓ 14-day sliding window
✓ Device column + date columns
✓ Two-tier rental bars (rental + logistics)
✓ Touch scrolling
✓ Weekend/today highlighting
✓ Click to show details

### RentalBottomSheet.vue (Details Modal)
✓ Bottom-slide animation
✓ Draggable handle
✓ 9 info fields displayed
✓ Status color-coded tags
✓ Edit button → router.push
✓ Delete with confirmation

### CreateRentalView.vue (New Rental)
✓ 5-section form layout
✓ Xianyu order auto-fetch
✓ Device model picker
✓ Date pickers (start/end)
✓ Accessory checkboxes
✓ Shipping info collection
✓ Form validation
✓ Conflict detection (via composable)

### GanttView.vue (Calendar Page)
✓ Nav-bar with date navigation
✓ 7-day window shifts
✓ Create button
✓ GanttGrid rendering
✓ Bottom sheet modal

---

## Styling Key Values

### Mobile (Vant)
```css
/* Sizes */
--device-col-width: 54px         /* Fixed device name column */
--row-height: 26px               /* Calendar row height */
--nav-bar-height: 46px           /* Top navigation */
--tabbar-height: 50px            /* Bottom tabs */

/* Colors */
--primary: #409eff               /* Element Blue */
--rental-bar: #409eff            /* Rental period bar */
--logistics-bar: #a0cfff         /* Logistics period bar */
--today-bg: rgba(64, 158, 255, 0.05)  /* Today highlight */
--weekend-bg: #fef9f0            /* Weekend highlight */

/* Fonts */
--device-name-size: 7px
--bar-label-size: 6px
--date-size: 9-10px

/* Spacing */
Row padding: 0 2px
Component gap: 4-12px
Form section gap: 12px
```

### Desktop (Element Plus)
```css
/* Colors */
--primary: #409eff
--success: #67c23a
--warning: #e6a23c
--danger: #f56c6c

/* Dark mode support */
Supports CSS custom properties for dark theme
Uses Element Plus dark/chalk theme
```

---

## Development Quick Reference

### Start Mobile Dev Server
```bash
cd frontend-mobile
npm install
npm run dev
# Vite server on http://localhost:5173 or similar
```

### Key Mobile Files to Modify
1. `GanttGrid.vue` - Calendar layout & positioning
2. `RentalBottomSheet.vue` - Modal styling & fields
3. `CreateRentalView.vue` - Form sections & validation
4. `GanttView.vue` - Page layout & navigation
5. `gantt.ts` (store) - Data loading & business logic

### Debugging
```bash
# Console messages
npm run dev              # Vite shows all errors
Vue DevTools extension  # Chrome/Firefox
Network tab            # Check API calls
```

### Build for Production
```bash
npm run build
# Outputs to dist/
# Served from /static/mobile-dist/ in production
```

