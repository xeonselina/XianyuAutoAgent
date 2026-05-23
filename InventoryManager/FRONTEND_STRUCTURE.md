# InventoryManager Frontend Structure

## Overview
The InventoryManager project has TWO separate frontend applications:
1. **Desktop Frontend** (`/frontend`) - Full-featured rental management system
2. **Mobile Frontend** (`/frontend-mobile`) - Optimized for mobile/tablet rental management

Both are Vue 3 + TypeScript applications with their own independent build processes and deployments.

---

## DESKTOP FRONTEND (`/frontend`)

### Technology Stack
- **Framework**: Vue 3 (Composition API + TypeScript)
- **UI Library**: Element Plus (enterprise component library)
- **State Management**: Pinia
- **HTTP Client**: Axios
- **Router**: Vue Router v4
- **Charts**: ECharts
- **Styling**: Scoped CSS with Element Plus theming
- **Date Handling**: Day.js
- **Build Tool**: Vite
- **Testing**: Vitest

### Core Application Structure
```
/frontend/src/
├── App.vue                          # Root component (simple RouterView)
├── main.ts                          # App initialization (Element Plus setup)
├── router/
│   └── index.ts                     # 11 routes (Gantt, Shipping, Statistics, etc.)
├── stores/
│   ├── gantt.ts                     # Main Gantt/Calendar store
│   ├── counter.ts                   # Demo store
│   └── inspection.ts                # Inspection records store
├── utils/
│   ├── dateUtils.ts                 # Date handling utilities
│   └── phoneExtractor.ts            # Phone number extraction
├── components/                      # Reusable components
│   ├── GanttChart.vue              # Main calendar/rental visualization
│   ├── GanttRow.vue                # Individual row in Gantt chart
│   ├── RentalTooltip.vue           # Tooltip for rental info
│   ├── BookingDialog.vue           # Dialog for creating/editing bookings
│   ├── ImagePreviewDialog.vue      # Image viewing modal
│   ├── rental/                     # Rental-specific components
│   │   ├── EditRentalDialogNew.vue # Main rental editing
│   │   ├── RentalBasicForm.vue     # Basic info form (customer, dates)
│   │   ├── RentalShippingForm.vue  # Shipping info form
│   │   ├── RentalAccessorySelector.vue # Accessory selection
│   │   ├── BatchPrintDialog.vue    # Batch printing dialog
│   │   ├── RentalActionButtons.vue # Action buttons
│   │   └── index.ts                # Component exports
│   ├── inspection/                 # Inspection components
│   │   ├── ChecklistForm.vue       # Inspection checklist
│   │   ├── DeviceSearchInput.vue   # Search component
│   │   ├── EditInspectionDialog.vue # Inspection editor
│   │   ├── InspectionRecordCard.vue # Display card
│   │   └── RentalInfoCard.vue      # Rental info display
│   ├── printing/
│   │   └── SimplifiedShippingSlip.vue # Shipping slip template
│   └── icons/                       # Icon components
├── views/                           # Page components
│   ├── GanttView.vue               # Main calendar view (Gantt chart)
│   ├── BatchShippingView.vue       # Batch shipping management
│   ├── BatchShippingOrderView.vue  # Batch order details
│   ├── RentalContractView.vue      # Rental contract display
│   ├── ShippingOrderView.vue       # Single shipping order
│   ├── StatisticsView.vue          # Dashboard statistics (ECharts)
│   ├── RentalStatsView.vue         # Rental cycle statistics
│   ├── SFTrackingView.vue          # S.F. Express tracking
│   ├── InspectionView.vue          # Device inspection workflow
│   ├── InspectionRecordsView.vue   # Inspection history
│   └── AboutView.vue               # About page
└── types/                           # TypeScript type definitions
```

### Key Features (Desktop)
1. **Gantt Chart Visualization** - Calendar-based rental scheduling with drag-drop
2. **Advanced Rental Management** - Full CRUD with accessories, shipping, accessories
3. **Batch Operations** - Batch shipping, batch printing of documents
4. **Statistics & Analytics** - Revenue, rental cycles, device utilization
5. **Inspection Workflow** - Device condition tracking pre/post rental
6. **S.F. Express Integration** - Waybill management and tracking
7. **Contract Generation** - Rental contract printing/export
8. **Device Management** - Inventory, models, accessories

### Router Configuration (11 routes)
- `/` - GanttView (main)
- `/gantt` - Redirect to home
- `/contract/:id` - RentalContractView
- `/shipping/:id` - ShippingOrderView
- `/batch-shipping-order` - BatchShippingOrderView
- `/batch-shipping` - BatchShippingView
- `/statistics` - StatisticsView
- `/rental-stats` - RentalStatsView
- `/sf-tracking` - SFTrackingView
- `/inspection` - InspectionView
- `/inspection-records` - InspectionRecordsView

---

## MOBILE FRONTEND (`/frontend-mobile`)

### Technology Stack
- **Framework**: Vue 3 (Composition API + TypeScript)
- **UI Library**: Vant (mobile-optimized component library)
- **State Management**: Pinia v2
- **HTTP Client**: Axios
- **Router**: Vue Router v4
- **Styling**: Scoped CSS with Vant theming
- **Date Handling**: Day.js
- **Build Tool**: Vite
- **Target**: Mobile/Tablet (Vue 3.5.13)

### Core Application Structure
```
/frontend-mobile/src/
├── App.vue                          # Root with bottom tabbar navigation
├── main.ts                          # App initialization (Vant setup)
├── router/
│   └── index.ts                     # 4 routes (Gantt, Batch Shipping, Create, Edit)
├── stores/
│   └── gantt.ts                     # Gantt store (rentals, devices, API calls)
├── utils/
│   ├── dateUtils.ts                 # Date formatting utilities
│   └── phoneExtractor.ts            # Phone extraction utility
├── composables/
│   └── useConflictDetection.ts      # Conflict detection logic
├── components/                      # Mobile-optimized components
│   ├── GanttGrid.vue               # Mobile Gantt/calendar grid (14-day view)
│   ├── RentalBottomSheet.vue       # Bottom sheet showing rental details
│   ├── BatchShippingCard.vue       # Shipping card in list
│   └── icons/ (if any)
├── views/                           # Page components (simplified for mobile)
│   ├── GanttView.vue               # Mobile Gantt calendar with nav-bar
│   ├── BatchShippingView.vue       # Batch shipping management
│   ├── CreateRentalView.vue        # Create new rental (COMPLEX FORM)
│   └── EditRentalView.vue          # Edit existing rental (COMPLEX FORM)
└── types/ (if any)
```

### Mobile-Specific Features
1. **14-Day Sliding Calendar** - Touch-friendly Gantt grid
2. **Bottom Sheet Details** - Rental info in modal (not dialog)
3. **Simplified Navigation** - Vant tabbar with 2 main tabs
4. **Form-First UX** - Heavy use of Vant form components
5. **Touch-Optimized** - Larger tap targets, vertical scrolling
6. **Keep-Alive Routes** - GanttView and BatchShippingView cached for performance

### Router Configuration (4 routes)
Base path: `/mobile/`
- `/gantt` - GanttView (main, with tabbar)
- `/batch-shipping` - BatchShippingView (with tabbar)
- `/create-rental` - CreateRentalView (no tabbar)
- `/edit-rental/:id` - EditRentalView (no tabbar)

### Mobile Navigation
Uses Vant `<van-tabbar>` component with 2 tabs:
- **甘特图** (Gantt Chart) - Calendar view
- **批量发货** (Batch Shipping) - Shipping management

---

## SHARED COMPONENTS & ARCHITECTURE

### State Management (Pinia Stores)
**Desktop & Mobile both use:**
```typescript
// gantt.ts
- devices: Device[]           // All devices
- rentals: Rental[]           // All rentals for date range
- currentDate: Date           // Current navigation date
- selectedDate: Date | null   // User selection
- loading: boolean            // API loading state
- error: string | null        // Error messages

// Key methods:
- loadData()                  // Fetch rentals & devices
- createRental(data)          // Create new
- updateRental(id, data)      // Update
- deleteRental(id)            // Delete
- navigateWeek(direction)     // Move week
- goToToday()                 // Jump to today
```

### Key Data Models
```typescript
interface Device {
  id: number
  name: string
  serial_number: string
  model: string
  model_id?: number
  device_model?: DeviceModel
  is_accessory: boolean
  status: 'online' | 'offline'
  lifecycle_status: 'active' | 'sold' | 'decommissioned' | 'damaged' | 'retired'
}

interface Rental {
  id: number
  device_id: number
  device?: Device                    // Device info
  start_date: string                 // Rental start (YYYY-MM-DD)
  end_date: string                   // Rental end (YYYY-MM-DD)
  customer_name: string
  customer_phone: string
  destination: string
  ship_out_tracking_no?: string
  ship_in_tracking_no?: string
  status: string                     // not_shipped | shipped | returned | etc.
  ship_out_time?: string             // Actual ship time
  ship_in_time?: string              // Actual return time
  accessories?: Accessory[]
  includes_handle: boolean           # Bundle marker
  includes_lens_mount: boolean       # Bundle marker
  photo_transfer: boolean            # Photo transfer flag
  xianyu_order_no?: string          # Xianyu order ID
  order_amount?: number
  buyer_id?: string
}
```

### Calendar/Gantt Logic
Both frontends visualize rental timelines:

**Desktop (GanttChart):**
- Full 30-day view with time scale at top
- Multiple rentals per device stacked vertically
- Drag-drop for schedule changes
- Tooltips on hover with full details
- Color-coded by status

**Mobile (GanttGrid):**
- 14-day sliding window (adjustable with arrow buttons)
- Compressed view (54px device column + 14 date columns)
- Two bars per rental:
  - Upper bar: Rental period (start_date → end_date)
  - Lower bar: Logistics period (ship_out_time → ship_in_time)
- Click to open bottom sheet with details
- Touch-friendly: 26px rows, small fonts (6-10px)

---

## FILE COUNT SUMMARY

### Desktop Frontend
- **Vue Components**: 40 files
  - Views: 12
  - Components: 28 (including icons, inspection, rental, printing subdirs)
- **TypeScript**: 4 files (stores x3, utils x2, router x1)
- **Config**: 6 files (tsconfig, vite.config, vitest.config, etc.)
- **Tests**: Vitest setup

### Mobile Frontend
- **Vue Components**: 8 files
  - Views: 4 (Gantt, BatchShipping, CreateRental, EditRental)
  - Components: 4 (GanttGrid, RentalBottomSheet, BatchShippingCard, + icons)
- **TypeScript**: 4 files (stores x1, composables x1, utils x2, router x1)
- **Config**: 4 files (tsconfig, vite.config, etc.)
- **Much simpler** than desktop - focused on core rental management

---

## KEY MOBILE UI COMPONENTS

### GanttGrid.vue (Mobile Calendar)
- 14-day sliding window calendar
- Device list on left, date columns on right
- Rental bars showing:
  - Blue upper bar: Customer rental period
  - Light blue lower bar: Logistics/shipping period
- Responsive grid: 54px device col + ~7% per date col
- Click rental bar → open RentalBottomSheet

### RentalBottomSheet.vue (Mobile Details)
- Bottom-slide modal with draggable handle
- Shows: Customer, dates, destination, status, tracking
- Actions: Edit button → router.push to EditRentalView
- Delete with confirmation
- Status tags with color coding

### CreateRentalView.vue & EditRentalView.vue
- Large, complex mobile forms using Vant
- Sections:
  1. Order Info (Xianyu order pull, customer name/phone, address, amount)
  2. Rental Dates (device model picker, start/end date)
  3. Accessories (checkbox selection from device model)
  4. Shipping Info (ship out/in dates, tracking numbers)
  5. Flags (handle included, lens mount, photo transfer)
- Form validation with required fields
- API submission with loading states

---

## API ENDPOINTS USED

Both frontends call these main endpoints:
```
GET  /api/gantt/data              # Fetch rentals & devices for date range
POST /api/rentals                 # Create rental
PUT  /api/rentals/:id             # Update rental
DELETE /api/rentals/:id           # Delete rental
POST /api/rentals/:id/ship-out    # Mark as shipped
POST /api/rentals/:id/ship-in     # Mark as returned
GET  /api/xianyu/orders/:orderNo  # Fetch Xianyu order details
# ... and many others for batch operations, statistics, etc.
```

---

## BUILD & DEPLOYMENT

### Desktop Build
```bash
cd frontend
npm run build              # Outputs to dist/
npm run type-check        # Type checking
```

### Mobile Build
```bash
cd frontend-mobile
npm run build             # Outputs to dist/
```

Both are served from `/static/` directory in production with separate base paths:
- Desktop: `/static/vue-dist/`
- Mobile: `/static/mobile-dist/` or `/mobile/`

---

## STYLING APPROACH

**Desktop**: Element Plus theming with custom CSS
- Dark mode support (CSS variables)
- Enterprise color scheme
- Responsive grid layouts

**Mobile**: Vant theming with custom CSS  
- Light, minimal theme
- Touch-friendly spacing
- CSS custom properties for primary color (--van-primary-color: #409eff)
- Full-height layouts with flex

---

## Development Workflow

### Desktop Development
```bash
cd frontend
npm run dev                # Starts Vite dev server on :5173
npm run test              # Run Vitest
npm run test:ui           # Vitest UI
```

### Mobile Development
```bash
cd frontend-mobile
npm run dev               # Starts Vite dev server
```

Both support hot module replacement (HMR) for instant refresh during development.
