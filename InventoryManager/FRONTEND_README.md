# InventoryManager Frontend - Complete Documentation

This directory contains comprehensive documentation for the InventoryManager frontend applications.

## 📚 Documentation Files

### 1. **FRONTEND_STRUCTURE.md** - Architecture & Overview
Read this first for a high-level understanding:
- Overview of two frontend apps (desktop & mobile)
- Tech stack for each
- Core application structure
- Key features and router configuration
- Shared components and state management
- File count summary
- Building and deployment

**Best for:** Understanding the project architecture, tech stack, and main features

---

### 2. **FRONTEND_COMPLETE_LISTING.md** - Detailed File Tree
Complete directory structure with file descriptions:
- Desktop frontend complete directory tree with every file described
- Mobile frontend complete directory tree
- Priority files for development
- Desktop vs Mobile comparison table

**Best for:** Finding specific files, understanding what each component does, file organization

---

### 3. **FRONTEND_VISUAL_GUIDE.md** - Visual & Conceptual
Diagrams and visual representations:
- Architecture overview diagram
- Component hierarchies
- State management structure
- Data models and interfaces
- Calendar visualization logic (desktop vs mobile)
- Mobile UI component mockups
- Navigation flows
- Styling reference values

**Best for:** Visual learners, understanding data flow, UI/UX details, design tokens

---

## 🎯 Quick Start by Use Case

### I want to...

**Understand the overall project**
→ Read: `FRONTEND_STRUCTURE.md` (Overview section)

**Work on mobile UI components**
→ Read: `FRONTEND_COMPLETE_LISTING.md` (Mobile Frontend section)
→ Then: `FRONTEND_VISUAL_GUIDE.md` (Mobile UI Component Details)

**Find a specific component**
→ Use: `FRONTEND_COMPLETE_LISTING.md` (search the file tree)

**Understand the calendar/Gantt visualization**
→ Read: `FRONTEND_VISUAL_GUIDE.md` (Calendar Visualization Logic section)

**Learn the state management (Pinia store)**
→ Read: `FRONTEND_VISUAL_GUIDE.md` (State Management section)

**Understand the data models (Device, Rental)**
→ Read: `FRONTEND_VISUAL_GUIDE.md` (Data Model section)

**Modify mobile form styling**
→ Read: `FRONTEND_COMPLETE_LISTING.md` (CreateRentalView details)
→ Then: `FRONTEND_VISUAL_GUIDE.md` (Styling Key Values)

**Debug mobile routing/navigation**
→ Read: `FRONTEND_VISUAL_GUIDE.md` (Navigation Flow section)

**Understand mobile calendar positioning**
→ Read: `FRONTEND_COMPLETE_LISTING.md` (GanttGrid.vue section)
→ Then: `FRONTEND_VISUAL_GUIDE.md` (GanttGrid.vue - Grid Layout)

---

## 🗂️ Directory Structure Summary

```
InventoryManager/
│
├── /frontend                    ← Desktop app (Vue 3 + Element Plus)
│   ├── src/
│   │   ├── views/              (12 pages)
│   │   ├── components/         (40 components)
│   │   ├── stores/             (Pinia store)
│   │   └── ...
│   └── package.json
│
├── /frontend-mobile             ← Mobile app (Vue 3 + Vant)
│   ├── src/
│   │   ├── views/              (4 pages)
│   │   ├── components/         (4 main components)
│   │   ├── stores/             (Pinia store)
│   │   └── ...
│   └── package.json
│
└── [This documentation]
    ├── FRONTEND_README.md       (this file)
    ├── FRONTEND_STRUCTURE.md    (architecture overview)
    ├── FRONTEND_COMPLETE_LISTING.md  (detailed file tree)
    └── FRONTEND_VISUAL_GUIDE.md (diagrams and mockups)
```

---

## 🔑 Key Concepts

### Two Separate Applications
1. **Desktop Frontend** (`/frontend`)
   - Full-featured rental management system
   - 12 pages, 40+ components
   - Element Plus UI library
   - For desktop/laptop use
   - Drag-drop, analytics, statistics

2. **Mobile Frontend** (`/frontend-mobile`)
   - Optimized for mobile/tablet
   - 4 core pages
   - Vant UI library
   - Simplified forms, touch-optimized
   - Focus on essential operations

### Shared State (Pinia Store)
Both apps use similar `gantt.ts` stores with:
- Device list
- Rental list
- Date navigation
- API integration

### Calendar Visualization
- **Desktop**: 30-day Gantt chart with drag-drop
- **Mobile**: 14-day grid with sliding window navigation

### Main Data Models
- **Device**: Equipment being rented (name, serial number, status)
- **Rental**: Rental transaction (customer, dates, shipping info, status)

---

## 🛠️ Development Tips

### Working on Mobile Components
1. Start with `GanttView.vue` (main page)
2. Then `GanttGrid.vue` (calendar component)
3. Then `RentalBottomSheet.vue` (details modal)
4. Then form pages (Create/Edit Rental)

### Understanding Mobile Forms
The forms are complex with multiple sections:
1. Order Info (customer details, order number)
2. Rental Dates (device selection, date pickers)
3. Accessories (checkboxes from device model)
4. Shipping Info (dates, times, tracking numbers)
5. Form Actions (submit button)

### Key Mobile Components
- **GanttGrid.vue**: 14-day calendar grid with rental bars
- **RentalBottomSheet.vue**: Bottom-slide modal showing rental details
- **CreateRentalView.vue**: Multi-section form for creating rentals
- **EditRentalView.vue**: Similar to create, but for editing

### Styling Notes
- Mobile uses Vant components with Vant theming
- Primary color: `#409eff` (Element Blue)
- Device column: 54px fixed, date columns: flex-based (~7% each)
- Row height: 26px, very compact

---

## 📊 Statistics

### Desktop Frontend
- **Vue Components**: 40 files
- **Views**: 12 pages
- **Components**: 28 reusable
- **Routes**: 11 pages
- **Code Lines**: ~5000+

### Mobile Frontend
- **Vue Components**: 8 files
- **Views**: 4 pages
- **Components**: 4 main
- **Routes**: 4 pages
- **Code Lines**: ~1500

**Total Frontend Code**: ~6500+ lines of Vue/TypeScript

---

## 🚀 Quick Commands

### Mobile Development
```bash
cd frontend-mobile
npm install
npm run dev        # Start dev server
npm run build      # Build for production
```

### Desktop Development
```bash
cd frontend
npm install
npm run dev        # Start dev server
npm run build      # Build for production
npm run test       # Run tests
```

---

## 📝 File Descriptions

### Mobile (Priority Order)

1. **GanttView.vue** (115 lines)
   - Main calendar page
   - Navigation bar with date controls
   - GanttGrid component
   - RentalBottomSheet modal

2. **GanttGrid.vue** (345 lines)
   - 14-day calendar grid
   - Device column + date columns
   - Rental bars (rental + logistics)
   - Positioning logic

3. **CreateRentalView.vue** (300+ lines)
   - Complex form with 5 sections
   - Vant form components
   - Accessory selection
   - Conflict detection

4. **EditRentalView.vue** (300+ lines)
   - Similar to CreateRentalView
   - Pre-population of fields
   - Update instead of create

5. **RentalBottomSheet.vue** (211 lines)
   - Modal showing rental details
   - 9 info fields
   - Edit/Delete buttons

6. **gantt.ts (Store)** (200+ lines)
   - State: devices, rentals, dates
   - Actions: CRUD operations
   - Getters: computed properties

### Desktop (Priority Order)

1. **GanttChart.vue** (1000+ lines)
   - Main calendar visualization
   - Toolbar with controls
   - Multiple GanttRow components
   - Drag-drop support

2. **EditRentalDialogNew.vue**
   - Dialog for rental editing
   - Composes sub-forms

3. **RentalBasicForm.vue**
   - Customer and order info

4. **RentalShippingForm.vue**
   - Shipping dates and tracking

---

## 🔗 References

### External Documentation
- [Vue 3 Docs](https://vuejs.org/)
- [Vant Component Library](https://vant-contrib.gitee.io/)
- [Element Plus Docs](https://element-plus.org/)
- [Pinia Store](https://pinia.vuejs.org/)
- [Vue Router](https://router.vuejs.org/)
- [Vite](https://vitejs.dev/)

### Related Backend
The frontends communicate with backend API at `/api/`:
- GET `/api/gantt/data` - Fetch rentals & devices
- POST `/api/rentals` - Create rental
- PUT `/api/rentals/:id` - Update rental
- DELETE `/api/rentals/:id` - Delete rental

---

## 💡 Common Tasks

### Add a new field to rental form
1. Find `CreateRentalView.vue` and `EditRentalView.vue`
2. Add `van-field` component in appropriate section
3. Update the form data object
4. Update type definitions in store
5. Update API call to include field

### Change calendar colors
1. Open `GanttGrid.vue` (mobile) or `GanttChart.vue` (desktop)
2. Find the color definitions in `<style scoped>`
3. Update the hex values
4. Or modify CSS custom properties

### Add new navigation route
1. Edit `router/index.ts`
2. Import the view component
3. Add route object to routes array
4. Update navigation links

### Modify form validation
1. Find the `van-field` component
2. Add/modify `:rules` prop
3. Validation runs on form submission

---

## 📌 Important Notes

1. **Two Separate Apps**: Desktop and mobile are separate applications with independent builds and deployments
2. **Shared Store**: Both use similar Pinia stores, but they're separate files
3. **API-Driven**: Both frontends fetch data from the same backend API
4. **Chinese Text**: UI contains Chinese labels (Vant and Element Plus are Chinese-first)
5. **Mobile-First**: Mobile app is optimized for touch and small screens
6. **Date Formats**: YYYY-MM-DD throughout (Day.js)

---

## ✅ Verification Checklist

When making changes, verify:
- [ ] Components render without errors
- [ ] Data loads from API correctly
- [ ] Forms submit and update state
- [ ] Navigation works as expected
- [ ] Mobile view is responsive
- [ ] No console errors or warnings
- [ ] Build completes successfully

---

**Last Updated**: 2026-05-23
**Total Documentation Files**: 4
**Total Documentation Lines**: ~2000+
