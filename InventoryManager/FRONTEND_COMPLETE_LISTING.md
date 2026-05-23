# Complete Frontend File Listing

## DESKTOP FRONTEND - Complete Directory Tree

```
/frontend/src/
│
├── App.vue
│   └── Simple root component with <RouterView />
│
├── main.ts
│   └── Vue 3 app initialization
│       - Element Plus setup
│       - Icons registration
│       - Pinia initialization
│       - Chinese locale configuration
│
├── router/
│   └── index.ts
│       - 11 routes defined
│       - Imports all 12 view components
│
├── stores/
│   ├── gantt.ts                 [MAIN DATA STORE]
│   │   - devices[], rentals[], currentDate
│   │   - loadData(), createRental(), updateRental(), deleteRental()
│   │   - navigateWeek(), goToToday()
│   │   - dateRange, currentPeriod, availableDevices computed properties
│   │   - getRentalsForDevice(deviceId)
│   │
│   ├── counter.ts               [DEMO STORE]
│   │   - Simple example counter store
│   │
│   └── inspection.ts            [INSPECTION STORE]
│       - Inspection records management
│       - Device condition tracking
│
├── utils/
│   ├── dateUtils.ts
│   │   - Date formatting and range calculations
│   │   - getCurrentDate(), toDateString(), formatDisplayDate()
│   │   - DateRangeUtils: getWeekRange(), getDayRange()
│   │
│   └── phoneExtractor.ts
│       - Phone number extraction from text
│       - Pattern matching utilities
│
├── components/
│   ├── GanttChart.vue           [PRIMARY CALENDAR COMPONENT]
│   │   - Toolbar with week navigation, date picker
│   │   - Filter controls for search
│   │   - Main Gantt visualization
│   │   - Multiple buttons: add device, booking, batch shipping
│   │   - Dropdown menu: statistics, rental stats, SF tracking, inspection
│   │   - Uses GanttRow sub-components
│   │
│   ├── GanttRow.vue
│   │   - Single device row in Gantt chart
│   │   - Rental bars with tooltips
│   │   - Drag-drop support
│   │
│   ├── RentalTooltip.vue
│   │   - Hover tooltip showing rental details
│   │   - Customer, dates, status information
│   │
│   ├── BookingDialog.vue        [RENTAL CREATION DIALOG]
│   │   - Create/edit rental in modal
│   │   - Form fields for basic rental info
│   │
│   ├── ImagePreviewDialog.vue
│   │   - Modal for viewing images
│   │   - Used for device/rental photos
│   │
│   ├── rental/                  [RENTAL MANAGEMENT COMPONENTS]
│   │   ├── EditRentalDialogNew.vue    [MAIN EDIT COMPONENT]
│   │   │   - Complex dialog for rental editing
│   │   │   - Composes all sub-forms below
│   │   │   - Submit/cancel handlers
│   │   │
│   │   ├── RentalBasicForm.vue
│   │   │   - Customer name, phone
│   │   │   - Destination address
│   │   │   - Order amount, buyer ID
│   │   │   - Xianyu order number
│   │   │
│   │   ├── RentalShippingForm.vue
│   │   │   - Ship out date/time
│   │   │   - Ship in date/time
│   │   │   - Tracking numbers (out/in)
│   │   │   - Shipping status
│   │   │
│   │   ├── RentalAccessorySelector.vue
│   │   │   - Multi-select accessory picker
│   │   │   - From device model accessories
│   │   │   - Bundled flag options
│   │   │
│   │   ├── RentalActionButtons.vue
│   │   │   - Action buttons row (ship, return, etc.)
│   │   │   - Status-based button visibility
│   │   │
│   │   ├── BatchPrintDialog.vue
│   │   │   - Print multiple shipping slips
│   │   │   - Batch document generation
│   │   │
│   │   └── index.ts
│   │       - Component exports/barrel file
│   │
│   ├── inspection/              [DEVICE INSPECTION COMPONENTS]
│   │   ├── ChecklistForm.vue
│   │   │   - Inspection checklist items
│   │   │   - Pass/fail conditions
│   │   │   - Photo uploads
│   │   │
│   │   ├── DeviceSearchInput.vue
│   │   │   - Device search/picker
│   │   │   - Autocomplete functionality
│   │   │
│   │   ├── EditInspectionDialog.vue
│   │   │   - Modal for editing inspection records
│   │   │   - Uses ChecklistForm
│   │   │
│   │   ├── InspectionRecordCard.vue
│   │   │   - Display single inspection record
│   │   │   - Read-only display card
│   │   │
│   │   └── RentalInfoCard.vue
│   │       - Display rental info in inspection context
│   │       - Device, customer, dates
│   │
│   ├── printing/
│   │   └── SimplifiedShippingSlip.vue
│   │       - Shipping slip template
│   │       - Printable layout for shipping
│   │
│   └── icons/                   [ICON COMPONENTS]
│       ├── IconCommunity.vue
│       ├── IconDocumentation.vue
│       ├── IconEcosystem.vue
│       ├── IconSupport.vue
│       └── IconTooling.vue
│
├── views/                       [PAGE COMPONENTS - 12 TOTAL]
│   ├── GanttView.vue
│   │   - Main application view
│   │   - Loads GanttChart component
│   │   - Full-height view, handles navigation
│   │
│   ├── BatchShippingView.vue
│   │   - Batch shipping management
│   │   - Lists pending rentals for shipping
│   │   - Multi-select for batch operations
│   │
│   ├── BatchShippingOrderView.vue
│   │   - Details of a batch shipping order
│   │   - Order contents and status
│   │
│   ├── RentalContractView.vue
│   │   - Display rental contract
│   │   - Printable rental agreement
│   │   - Route param: /contract/:id
│   │
│   ├── ShippingOrderView.vue
│   │   - Single shipping order details
│   │   - Route param: /shipping/:id
│   │   - Tracking, waybill info
│   │
│   ├── StatisticsView.vue
│   │   - Dashboard with statistics
│   │   - ECharts visualizations
│   │   - Revenue, device utilization, etc.
│   │
│   ├── RentalStatsView.vue
│   │   - Rental cycle analytics
│   │   - Duration statistics
│   │   - Customer rental patterns
│   │
│   ├── SFTrackingView.vue
│   │   - S.F. Express (顺丰) tracking
│   │   - Waybill tracking integration
│   │   - Shipment status lookup
│   │
│   ├── InspectionView.vue
│   │   - Device inspection workflow
│   │   - Start inspection process
│   │   - Uses ChecklistForm component
│   │
│   ├── InspectionRecordsView.vue
│   │   - List of inspection records
│   │   - History and search
│   │   - Uses InspectionRecordCard components
│   │
│   ├── AboutView.vue
│   │   - About page / app info
│   │
│   └── (implicit) RentalContractView used in /contract/:id route
│
├── api/
│   - API client modules (if any - check for api/ folder)
│
├── composables/
│   - Vue 3 composable functions (if any)
│
├── types/
│   - TypeScript type definitions
│
├── assets/
│   - Images, fonts, logos
│   - main.css (global styles)
│
└── [config files at root]
    - tsconfig.json
    - tsconfig.app.json
    - tsconfig.node.json
    - vite.config.ts
    - vitest.config.ts
    - env.d.ts
    - auto-imports.d.ts
    - components.d.ts
```

---

## MOBILE FRONTEND - Complete Directory Tree

```
/frontend-mobile/src/
│
├── App.vue                      [ROOT APP]
│   - Router view with keep-alive
│   - Vant tabbar navigation
│   - Bottom tab bar with 2 items:
│     1. 甘特图 (Gantt)
│     2. 批量发货 (Batch Shipping)
│   - Conditional tabbar visibility (not on create/edit pages)
│
├── main.ts
│   - Vue 3 app initialization
│   - Vant UI library setup
│   - Pinia store initialization
│   - Router initialization
│
├── router/
│   └── index.ts                 [4 ROUTES DEFINED]
│       ✓ /gantt (name: 'gantt')              → GanttView
│       ✓ /batch-shipping (name: 'batch-shipping') → BatchShippingView
│       ✓ /create-rental (name: 'create-rental')  → CreateRentalView
│       ✓ /edit-rental/:id (name: 'edit-rental')  → EditRentalView
│       Base path: '/mobile/'
│       Keep-alive for: GanttView, BatchShippingView
│
├── stores/
│   └── gantt.ts                 [PRIMARY STATE STORE]
│       - devices: Device[]      // All available devices
│       - rentals: Rental[]      // Current date range rentals
│       - currentDate: Date      // Current navigation date
│       - selectedDate: Date | null
│       - loading: boolean
│       - error: string | null
│       
│       Methods:
│       • loadData()             // Fetch rentals & devices
│       • createRental(data)     // POST to /api/rentals
│       • updateRental(id, data) // PUT to /api/rentals/:id
│       • deleteRental(id)       // DELETE to /api/rentals/:id
│       • navigateWeek(days)     // Move date window
│       • goToToday()            // Jump to today
│       • getRentalsForDevice(deviceId)
│       
│       Computed:
│       • dateRange
│       • currentPeriod
│       • availableDevices
│
├── composables/
│   └── useConflictDetection.ts
│       - Detect scheduling conflicts
│       - Check device availability
│       - Handle overlapping rentals
│
├── utils/
│   ├── dateUtils.ts
│   │   - getCurrentDate()       // Return today as dayjs
│   │   - toDateString(date)     // Format to YYYY-MM-DD
│   │   - formatDisplayDate(date, format)
│   │   - DateRangeUtils.getWeekRange()
│   │
│   └── phoneExtractor.ts
│       - Extract phone numbers from text
│       - Parse and validate phone format
│
├── components/                  [MOBILE COMPONENTS - 8 TOTAL]
│   │
│   ├── GanttGrid.vue           [MAIN CALENDAR COMPONENT]
│   │   - 14-day sliding window calendar grid
│   │   - Props:
│   │     * devices: Device[]
│   │     * rentals: Rental[]
│   │     * windowStart: string (YYYY-MM-DD)
│   │     * loading: boolean
│   │   - Emits: bar-click(rental)
│   │   
│   │   Structure:
│   │   - Header row: device column + 14 date columns
│   │   - Device list rows
│   │   - For each rental, 2 bars:
│   │     1. Upper bar (blue): Rental period (start_date to end_date)
│   │     2. Lower bar (light blue): Logistics (ship_out_time to ship_in_time)
│   │   
│   │   Styling:
│   │   - Device col: 54px fixed width
│   │   - Date cols: flex-based, ~7% each
│   │   - Row height: 26px
│   │   - Fonts: 7px device name, 6px bar labels
│   │   - Colors: #409eff (primary blue), light variations
│   │   
│   │   Features:
│   │   - Click rental bar → emit bar-click event
│   │   - Weekend highlighting (orange background)
│   │   - Today highlighting (blue background)
│   │   - Touch-friendly scrolling (-webkit-overflow-scrolling: touch)
│   │   - Grid lines with 1px borders
│   │
│   ├── RentalBottomSheet.vue   [RENTAL DETAILS MODAL]
│   │   - Props:
│   │     * modelValue: boolean  (v-model)
│   │     * rental: Rental | null
│   │   - Emits:
│   │     * update:modelValue(val)
│   │     * closed()
│   │     * deleted()
│   │   
│   │   Content:
│   │   - Drag handle (visual affordance)
│   │   - Device name as title
│   │   - Info grid with labels:
│   │     * 租客 (Customer)
│   │     * 发货日 (Ship out date)
│   │     * 起租日 (Rental start)
│   │     * 还租日 (Rental end)
│   │     * 入库日 (Ship in date)
│   │     * 地址 (Address) - 2-line clamp
│   │     * 运单号 (Tracking number)
│   │     * 状态 (Status) - color-coded tag
│   │   - Action buttons:
│   │     * Edit → router.push to edit-rental/:id
│   │     * Delete → confirm dialog → API call
│   │   
│   │   Status colors:
│   │   - not_shipped: #ff976a (orange)
│   │   - scheduled_for_shipping: #1989fa (blue)
│   │   - shipped: #07c160 (green)
│   │   - returned: #7232dd (purple)
│   │   - completed: #333 (dark)
│   │   - cancelled: #999 (gray)
│   │
│   ├── BatchShippingCard.vue
│   │   - Card component for batch shipping list
│   │   - Display shipping item info
│   │   - Clickable for detail view
│   │
│   └── [icons/ subdirectory if any]
│
├── views/                       [PAGE COMPONENTS - 4 TOTAL]
│   │
│   ├── GanttView.vue           [MAIN CALENDAR PAGE]
│   │   - Van-nav-bar with:
│   │     LEFT: Date navigation arrows + date range label
│   │     RIGHT: "新建" (Create) button
│   │   - GanttGrid component (main content)
│   │   - RentalBottomSheet (modal)
│   │   
│   │   Events:
│   │   - Bar click → open bottom sheet
│   │   - Create button → router.push('create-rental')
│   │   - Edit in sheet → router.push('edit-rental/:id')
│   │   - Delete in sheet → reload data
│   │   - Tab bar change → navigate
│   │   
│   │   Window:
│   │   - 14 days displayed
│   │   - Shifts by 7 days with arrow buttons
│   │   - Shows date range in label
│   │
│   ├── BatchShippingView.vue   [BATCH SHIPPING PAGE]
│   │   - Tab-bar visible
│   │   - List of items pending shipping
│   │   - Select multiple items
│   │   - Batch actions (print, confirm ship)
│   │   - Uses BatchShippingCard components
│   │
│   ├── CreateRentalView.vue    [CREATE RENTAL FORM - COMPLEX]
│   │   - Van-nav-bar with back button
│   │   - Full-page form with sections:
│   │   
│   │   1. ORDER INFO (van-cell-group)
│   │      • Xianyu order number (with fetch button)
│   │      • Customer name (required)
│   │      • Customer phone (optional)
│   │      • Destination address (textarea)
│   │      • Order amount (optional)
│   │      • Buyer ID (optional)
│   │   
│   │   2. RENTAL DATES (van-cell-group)
│   │      • Device model (picker, required)
│   │      • Start date (date picker, required)
│   │      • End date (date picker, required)
│   │      • Rental duration display
│   │      • Conflict detection
│   │   
│   │   3. ACCESSORIES (van-cell-group)
│   │      • From device model accessories list
│   │      • Checkboxes for selection
│   │      • Bundled flags (handle, lens mount)
│   │      • Photo transfer flag
│   │   
│   │   4. SHIPPING INFO (van-cell-group)
│   │      • Ship out date (date picker)
│   │      • Ship out time (time picker)
│   │      • Ship in date (date picker)
│   │      • Ship in time (time picker)
│   │      • Tracking numbers (outbound, inbound)
│   │      • Shipping status
│   │   
│   │   5. FORM ACTIONS
│   │      • Submit button (POST to /api/rentals)
│   │      • Loading state
│   │      • Validation
│   │      • Error handling
│   │   
│   │   Features:
│   │   - Vant form validation
│   │   - Fetch Xianyu order (auto-fill customer)
│   │   - Date range validation
│   │   - Conflict detection with existing rentals
│   │   - Device model picker with accessories
│   │   - Loading states during submission
│   │
│   └── EditRentalView.vue      [EDIT RENTAL FORM - COMPLEX]
│       - Similar structure to CreateRentalView
│       - Pre-populated form fields
│       - Route param: :id
│       - PUT to /api/rentals/:id instead of POST
│       - Pre-load rental data from store/API
│       - Delete button option
│
├── assets/
│   - Images, fonts
│
└── [config files at root]
    - tsconfig.json
    - vite.config.ts
```

---

## KEY FILES FOR MOBILE UI DEVELOPMENT

### Priority 1 - Core Calendar Logic
1. `frontend-mobile/src/components/GanttGrid.vue` (345 lines)
   - Responsive grid with 14-day window
   - Rental bar positioning logic
   - Header with date columns

2. `frontend-mobile/src/views/GanttView.vue` (115 lines)
   - Navigation controls
   - Date window management
   - Sheet interaction

### Priority 2 - Rental Forms
3. `frontend-mobile/src/views/CreateRentalView.vue` (300+ lines)
   - Complex multi-section form
   - Vant components usage
   - Accessory selection
   - Conflict detection

4. `frontend-mobile/src/views/EditRentalView.vue` (300+ lines)
   - Edit variant of above
   - Pre-population logic

### Priority 3 - Supporting Components
5. `frontend-mobile/src/components/RentalBottomSheet.vue` (211 lines)
   - Modal display
   - Status formatting
   - Edit/Delete actions

6. `frontend-mobile/src/stores/gantt.ts` (200+ lines)
   - State management
   - API integration
   - Data loading

### Priority 4 - Utilities
7. `frontend-mobile/src/utils/dateUtils.ts`
   - Date formatting
   - Range calculations

8. `frontend-mobile/src/composables/useConflictDetection.ts`
   - Scheduling logic

---

## COMPARISON: Desktop vs Mobile

| Aspect | Desktop | Mobile |
|--------|---------|--------|
| **UI Library** | Element Plus | Vant |
| **Calendar** | Full 30-day Gantt | 14-day grid |
| **Interaction** | Drag-drop, hover | Tap, swipe, bottom sheet |
| **Views** | 12 full pages | 4 focused pages |
| **Components** | 40+ detailed | 8 optimized |
| **Forms** | Dialog-based | Full-page forms |
| **Navigation** | Sidebar/menu | Bottom tabbar |
| **Target Device** | Desktop/laptop | Mobile/tablet |
| **Complexity** | High (analytics, statistics) | Medium (core operations) |
| **Line Count** | ~5000+ lines | ~1500 lines |

