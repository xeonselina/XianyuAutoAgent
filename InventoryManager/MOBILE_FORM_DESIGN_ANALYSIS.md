# Mobile Rental Form Design Analysis

**Date**: May 19, 2026  
**Purpose**: Technical deep-dive for designing a mobile-optimized rental form  
**Status**: Complete analysis of both CREATE (BookingDialog) and EDIT (EditRentalDialogNew) modes

---

## Executive Summary

The rental system has **two distinct form modes** with significant differences:
- **CREATE (BookingDialog.vue)**: 14 fields, 1 major async operation (order fetch), duplicate detection
- **EDIT (EditRentalDialogNew.vue)**: 13 fields (no start_date, no customer_name), complex data transformation, conflict detection

Mobile challenge: **Both forms are currently 600px wide, desktop-only dialogs**. Key complexity drivers for mobile:
1. **14-13 form fields** requiring careful grouping/sectioning
2. **3 async operations** that need spinners: order fetch, device conflict check, accessory availability check
3. **Conditional visibility** on 4+ fields based on state
4. **Auto-fill dependencies**: destination → phone extraction, order fetch → 4-field fill
5. **Data transformation**: Between UI format (bundledAccessories array, phoneHolderId number) and API format (includes_handle boolean)

---

## Form Structure Comparison

### CREATE Mode (BookingDialog.vue: 832 lines)

**14 Form Fields Organized in 3 Sections:**

```
┌─ Section 1: Date & Logistics (3 fields)
│  ├─ startDate (date picker, required, controls endDate min-date)
│  ├─ endDate (date picker, required, auto-calculates min-date)
│  └─ logisticsDays (input-number 0-7, required)
│
├─ Section 2: Order Info (1 field + button that triggers auto-fill)
│  ├─ xianyuOrderNo (text input, optional)
│  └─ [拉取订单信息] button → auto-fills 4 fields: destination, buyerId, orderAmount, customerPhone
│
├─ Section 3: Device Selection (2 fields + find-slot button)
│  ├─ selectedDeviceId (select dropdown, required for submit)
│  └─ [查找档期] button → async search for available device+times
│
├─ Section 4: Customer Info (4 fields, 1 watch-dependent)
│  ├─ customerName (text input, required)
│  ├─ customerPhone (text input, optional, can auto-extract from destination)
│  ├─ destination (textarea 3 rows, optional, triggers phone extraction watch)
│  └─ orderAmount (number input, optional)
│  └─ buyerId (text input, disabled/read-only)
│
├─ Section 5: Bundled Accessories (1 field)
│  ├─ bundledAccessories (checkbox-group: [handle, lens_mount])
│
├─ Section 6: Additional Services (1 field)
│  ├─ photoTransfer (single checkbox)
│
├─ Section 7: Inventory Accessories (2 fields + focus → availability check)
│  ├─ phoneHolderId (select dropdown, optional, shows availability tags)
│  └─ tripodId (select dropdown, optional, shows availability tags)
│
└─ Section 8: Results Display (conditional)
   └─ availableSlot (info box if slot found)
```

**Key State Management (8 refs):**
- `form` (main form object)
- `submitting` (submit loading)
- `searching` (find-slot loading)
- `fetchingOrder` (order fetch loading)
- `availableSlot` (result of find-slot)
- `availability.deviceAvailability` (computed, checked state)
- `availability.accessoryAvailability` (computed, checked state)

---

### EDIT Mode (EditRentalDialogNew.vue: 580 lines)

**13 Form Fields Organized in 3 Sections:**

```
┌─ Section 1: Action Buttons (top, before form)
│  ├─ [租赁合同] button → open URL in new tab
│  ├─ [发货单] button → open URL in new tab
│  ├─ [发货到闲鱼] button (conditional: requires xianyu_order_no + ship_out_tracking_no)
│  └─ [删除租赁] button
│
├─ Section 2: Basic Info (4 fields, mostly display-only)
│  ├─ deviceId (select dropdown, required, triggers conflict check)
│  ├─ customer_name (disabled/read-only)
│  ├─ start_date (disabled/read-only)
│  ├─ endDate (date picker, required)
│  ├─ xianyuOrderNo (text input + fetch button, similar to CREATE)
│  ├─ orderAmount (number input)
│  └─ buyerId (disabled/read-only)
│
├─ Section 3: Shipping & Status (7 fields)
│  ├─ customerPhone (text input)
│  ├─ destination (textarea, triggers phone extraction watch)
│  ├─ shipOutTrackingNo (text input + query button)
│  ├─ shipInTrackingNo (text input + query button)
│  ├─ shipOutTime (date-time picker)
│  ├─ shipInTime (date-time picker)
│  └─ status (select dropdown: not_shipped/shipped/returned/completed/cancelled)
│
├─ Section 4: Accessories (similar to CREATE)
│  ├─ bundledAccessories (checkbox-group)
│  ├─ photoTransfer (checkbox)
│  ├─ phoneHolderId (select)
│  ├─ tripodId (select)
│  └─ [已选择的附件汇总] display section
│
└─ Section 5: Top Action Buttons
   ├─ [Cancel] button
   └─ [Save] button with submit loading state
```

**Key State Management (7 refs):**
- `form` (13 fields)
- `submitting` (submit loading)
- `loadingLatestData` (fetch current data on open)
- `latestDataError` (error message)
- `deviceConflictChecked` (flag to prevent double-check)
- `accessoryConflictChecked` (flag to prevent double-check)

---

## Async Operations (Mobile Complexity Drivers)

### CREATE Mode

#### 1. Order Fetch: `POST /api/rentals/fetch-xianyu-order`

**Trigger**: User clicks [拉取订单信息] button after entering xianyuOrderNo

**Request**:
```typescript
{
  order_no: string  // e.g., "123456789"
}
```

**Response** (on success):
```typescript
{
  success: true,
  data: {
    receiver_name: string      // → destination part 1
    receiver_mobile: string    // → destination part 2 + customerPhone
    prov_name: string         // → destination part 3 (address)
    city_name: string         // → destination part 3
    area_name: string         // → destination part 3
    town_name: string         // → destination part 3
    address: string           // → destination part 3
    buyer_nick: string        // → customerName
    buyer_eid: string         // → buyerId
    pay_amount: number        // → orderAmount (divide by 100)
  }
}
```

**Auto-fills** (in order):
1. `customerName` ← `buyer_nick`
2. `destination` ← concatenate receiver_name + receiver_mobile + full_address
3. `buyerId` ← `buyer_eid`
4. `orderAmount` ← `pay_amount / 100`
5. `customerPhone` ← `receiver_mobile` (overwrites any watch-extracted value)

**UI State During**: `fetchingOrder = true` (button shows loading spinner)

**Mobile Issue**: After successful fetch, 4 fields change instantly. Need to indicate which fields were auto-filled.

---

#### 2. Device Availability Check: `ganttStore.checkDeviceConflict()`

**Trigger**: 
- User opens device selector dropdown OR
- User changes selectedDeviceId

**Logic** (useConflictDetection.ts):
```typescript
checkDeviceConflict({
  deviceId: number,
  startDate: Date | string,
  endDate: Date | string,
  excludeRentalId?: number
})
```

**Updates State**:
```typescript
availability.deviceAvailability = {
  checked: true,
  availableItems: DeviceWithStatus[],
  unavailableItems: DeviceWithStatus[]
}
```

**Display Effect**: Device options show colored tags:
- ✅ "可用" (green) if available
- ❌ "档期不可用" (red) if conflicted

**Mobile Issue**: Availability check runs on dropdown focus. If network is slow, user may see loading state before dropdown opens. Need clear loading indicator.

---

#### 3. Find Available Slot: `ganttStore.findAvailableSlot()`

**Trigger**: User clicks [查找档期] button

**Prerequisites**:
```typescript
canSearchSlot = computed(() => {
  return form.value.startDate && 
         form.value.endDate && 
         form.value.logisticsDays >= 0
})
```

**Request**:
```typescript
findAvailableSlot(
  startDate: 'YYYY-MM-DD',
  endDate: 'YYYY-MM-DD',
  logisticsDays: number,
  modelId: string,  // Device model ID (e.g., "1")
  isAccessory: boolean  // false for devices
)
```

**Response** (on success):
```typescript
{
  device: {
    id: number,
    name: string,
    model: string,
    // ... other device fields
  },
  shipOutDate: Date,
  shipInDate: Date
}
```

**Auto-fills**:
1. `selectedDeviceId` ← `device.id`
2. Shows info box: `availableSlot` with device name + times

**UI State During**: `searching = true` (button shows loading spinner)

**Mobile Issue**: Complex prerequisite (requires dates + logistics days first). Info box shows below form if slot found. May need rethinking on mobile.

---

### EDIT Mode

#### 1. Load Latest Data: `ganttStore.getRentalById()`

**Trigger**: Dialog opens (if `props.rental` changes)

**Purpose**: Refresh data before form initializes (might have changed externally)

**Response**: Full rental object with latest values

**Transformation** (complex):
```typescript
// API format → UI format
const bundledAccessories: ('handle' | 'lens_mount')[] = []
if (rentalData.includes_handle) bundledAccessories.push('handle')
if (rentalData.includes_lens_mount) bundledAccessories.push('lens_mount')

// Accessory extraction
const phoneHolder = rentalData.accessories.find(a => 
  a.type === 'phone_holder' || a.name?.includes('手机支架') || ...
)
const tripod = rentalData.accessories.find(a => 
  a.type === 'tripod' || a.name?.includes('三脚架') || ...
)

// Form initialization
form.value = {
  deviceId: rentalData.device_id,
  bundledAccessories,
  phoneHolderId: phoneHolder?.id || null,
  tripodId: tripod?.id || null,
  // ... other 10 fields
}
```

**UI State During**: `loadingLatestData = true` (shows loading tip above form)

**Mobile Issue**: Data transformation is complex. If accessories array structure changes, matching logic breaks.

---

#### 2. Device Conflict Check: `handleDeviceChange()` → `conflictDetection.checkDeviceConflict()`

**Trigger**: User changes device selector

**Request**:
```typescript
{
  deviceId: number,
  startDate: rentalData.ship_out_time || rentalData.start_date,
  endDate: rentalData.ship_in_time || rentalData.end_date,
  excludeRentalId: props.rental.id  // Don't check against self
}
```

**Result**: If conflict exists, shows dialog:
```
"设备 "{deviceName}" 在该时间段有冲突，确定要选择吗？"
```

User can confirm or cancel (reverts to previous deviceId).

**Mobile Issue**: Dialog on top of form on mobile is cramped. Might need redesign.

---

#### 3. Accessory Availability Check: `findAvailableAccessory()`

**Trigger**: User opens accessory dropdown OR
Function also called in `handleAccessorySelectorFocus()`

**Logic**:
```typescript
const slotResponse = await ganttStore.findAvailableSlot(
  startDate: rentalData.start_date,
  endDate: rentalData.end_date,
  logisticsDays: 1,  // hardcoded
  modelId: 1,  // X200U model ID (hardcoded)
  isAccessory: true
)

// Updates accessory availability state
deviceManagement.accessories.value.forEach(accessory => {
  if (accessory.model?.includes('手柄')) {
    accessory.isAvailable = availableDeviceIds.includes(accessory.id)
    accessory.conflictReason = accessory.isAvailable ? undefined : '档期冲突'
  }
})
```

**Mobile Issue**: Only updates **handle** accessories availability. Tripod logic not found (TODO in comments). Hardcoded values suggest incomplete feature.

---

## Data Flow & Transformations

### CREATE Mode: Destination Field Dependencies

```
User enters destination (textarea)
    ↓
watch() triggers on destination change
    ↓
If customerPhone is empty AND destination has phone number:
    ├─ extractPhoneNumber() extracts phone using regex
    ├─ customerPhone auto-fills
    └─ ElMessage.success('已自动从收件信息中提取手机号')
```

**Regex** (from phoneExtractor.ts, not shown but used):
```
/^1[3-9]\d{9}$/  // Chinese mobile numbers
```

**Problem**: If user manually enters phone, then enters destination, phone gets overwritten.

---

### CREATE Mode: Order Fetch Auto-Fill Chain

```
User enters xianyuOrderNo → clicks [拉取订单信息]
    ↓
fetchingOrder = true (button loading)
    ↓
POST /api/rentals/fetch-xianyu-order { order_no }
    ↓
Response.success = true?
    ├─ YES: Auto-fill 5 fields in sequence
    │  1. customerName ← buyer_nick
    │  2. destination ← receiver_name + receiver_mobile + address parts
    │  3. buyerId ← buyer_eid  
    │  4. orderAmount ← pay_amount / 100
    │  5. customerPhone ← receiver_mobile (overwrites extraction if any)
    │  └─ ElMessage.success('订单信息获取成功')
    │
    ├─ NO: Show error message
    └─ Finally: fetchingOrder = false
```

**Mobile Implication**: 5 fields changing at once without any visual indication of which ones changed. User may not notice auto-fills.

---

### CREATE → Submit: Form Validation + Duplicate Check + Submission

```
User clicks [提交预定]
    ↓
formRef.validate() 
    ├─ Required: startDate, endDate, logisticsDays, customerName
    └─ Optional with regex: customerPhone (if filled)
    ↓
PASS? → Continue : FAIL? → Show validation errors, stop
    ↓
conflictDetection.checkDuplicateRental({
  customerName: string,
  destination: string
})
    ↓
hasDuplicate?
    ├─ YES: Show dialog with duplicate rentals list
    │  User can:
    │  ├─ Confirm: "继续创建"
    │  └─ Cancel: Stop, dialog closes
    │
    ├─ NO: Skip dialog
    └─ → Continue
    ↓
submitting = true
    ↓
Transform UI format → API format:
{
  device_id: selectedDeviceId or availableSlot.device.id,
  start_date: 'YYYY-MM-DD',
  end_date: 'YYYY-MM-DD',
  ship_out_time: dayjs(shipOutTime).format('YYYY-MM-DD HH:mm:ss'),
  ship_in_time: dayjs(shipInTime).format('YYYY-MM-DD HH:mm:ss'),
  includes_handle: bundledAccessories.includes('handle'),
  includes_lens_mount: bundledAccessories.includes('lens_mount'),
  accessories: [phoneHolderId, tripodId].filter(id => id !== null),
  // ... 8 more fields
}
    ↓
ganttStore.createRental(rentalData)
    ↓
Success?
    ├─ YES: ElMessage.success('租赁记录创建成功')
    │        emit('success')
    │        handleClose() → reset all fields
    │        Close dialog
    │
    └─ NO: ElMessage.error('创建失败: ' + errorMessage)
        submitting = false
```

---

### EDIT → Submit: Similar but with updates

```
User clicks [保存]
    ↓
formRef.validate()
    ├─ Required: deviceId, endDate
    └─ Optional: customerPhone (regex if filled)
    ↓
PASS? → Continue : FAIL? → Show errors, stop
    ↓
submitting = true
    ↓
Transform UI format → API format:
{
  device_id: form.deviceId,
  end_date: dayjs(form.endDate).format('YYYY-MM-DD'),
  includes_handle: bundledAccessories.includes('handle'),
  includes_lens_mount: bundledAccessories.includes('lens_mount'),
  accessories: [phoneHolderId, tripodId].filter(id => id !== null),
  // ... 10 more fields
}
    ↓
ganttStore.updateRental(rentalId, updateData)
    ↓
Success? → Close dialog, emit('success')
Fail? → Show error message
```

---

## Field Validation Rules

**getEditRentalRules()** (useRentalFormValidation.ts):

```typescript
{
  deviceId: [
    { required: true, message: '请选择设备', trigger: 'change' }
  ],
  endDate: [
    { required: true, message: '请选择结束日期', trigger: 'change' }
  ],
  customerPhone: [
    { 
      pattern: /^1[3-9]\d{9}$/, 
      message: '请输入正确的手机号码', 
      trigger: 'blur' 
    }
  ]
  // No validation on other fields
}
```

**getCreateRentalRules()**:

```typescript
{
  startDate: [
    { required: true, message: '请选择开始日期', trigger: 'change' }
  ],
  endDate: [
    { required: true, message: '请选择结束日期', trigger: 'change' }
  ],
  logisticsDays: [
    { required: true, message: '请输入物流天数', trigger: 'change' }
  ],
  customerName: [
    { required: true, message: '请输入闲鱼ID', trigger: 'blur' }
  ],
  customerPhone: [
    { 
      pattern: /^1[3-9]\d{9}$/, 
      message: '请输入正确的手机号码', 
      trigger: 'blur' 
    }
  ]
}
```

---

## Critical UI/UX Issues for Mobile

### 1. Form Width & Height
- **Current**: 600px width desktop dialog
- **Mobile Challenge**: Need responsive width (100% minus padding) + likely > 2000px total height when scrolled
- **Consideration**: Consider collapsible sections or multi-step form

### 2. Async Operations Need Clear Feedback
- Order fetch: 1-2 second network latency
- Device conflict check: 1-2 second network latency
- Both show only loading spinner, no clear "what's loading" messaging

### 3. Auto-Fill Lacks Visibility
- Order fetch auto-fills 5 fields (customerName, destination, buyerId, orderAmount, customerPhone)
- User may not notice which fields changed
- No "filled" visual indicator or highlight

### 4. Accessory Type Matching Uses String Matching
```typescript
a.name.includes('手机支架') || a.name.toLowerCase().includes('phone') ||
(a.model && (a.model.includes('手机支架') || a.model.toLowerCase().includes('phone')))
```
- Brittle: relies on exact string contains
- If accessory name changes, matching breaks
- No clear categorization in backend

### 5. Device/Accessory Availability Tags
- Shows "可用" / "档期不可用" tags
- But availability check is async and happens on dropdown focus
- On mobile, this may cause dropdown to load slowly first time

### 6. Phone Extraction Logic
- Watches `destination` field
- Extracts phone using regex `/^1[3-9]\d{9}$/`
- Only works if customerPhone is empty
- But order fetch can overwrite this, causing confusion

### 7. Duplicate Detection (CREATE only)
- Checks by `customerName` + `destination`
- Shows dialog with list of duplicates
- User must read and confirm/cancel
- On mobile, this dialog may be hard to read

### 8. Data Transformation Complexity (EDIT)
- From API: `includes_handle` (boolean) + `includes_lens_mount` (boolean) + `accessories` (array of objects)
- To UI: `bundledAccessories` (array of strings) + `phoneHolderId` (number) + `tripodId` (number)
- Transform logic uses fragile string matching to find phone holder / tripod

---

## Mobile Redesign Recommendations

### 1. Sectioned, Collapsible Form
Instead of one long form, use accordion sections:
- **Section 1: Date & Logistics** (always open)
- **Section 2: Device** (collapsible)
- **Section 3: Customer Info** (collapsible)
- **Section 4: Accessories** (collapsible)
- **Section 5: Advanced** (collapsible, for tracking numbers, times)

### 2. Visual Feedback for Async Operations
Show a banner instead of just spinner:
```
⏳ Checking device availability... Please wait
```
or
```
✅ Order info loaded! 5 fields auto-filled (highlighted)
```

### 3. Highlight Auto-Filled Fields
After order fetch, temporarily highlight the 5 fields that changed:
```css
.auto-filled {
  background: rgba(24, 144, 255, 0.1);
  transition: all 0.3s ease-out;
}
/* Fade out after 3 seconds */
```

### 4. Better Phone Extraction UX
Instead of auto-extracting, show a suggestion:
```
📞 Detected phone number in address: 13800138000
[Use it] [Ignore]
```

### 5. Simplify Accessory Matching
Backend should assign `type: 'phone_holder' | 'tripod' | 'handle' | 'other'` to each accessory instead of string matching on frontend.

### 6. Combine Order Fetch + Auto-Fill
Instead of separate button, make it part of submission:
```
User enters xianyuOrderNo
    ↓ (auto-fetch on blur or next field focus)
Auto-fetch happens silently in background
    ↓
If success, fields auto-fill with highlight
If error, show inline error under xianyuOrderNo field
```

### 7. Redesign Duplicate Detection
Instead of blocking dialog, show inline warning:
```
⚠️ Similar rental found:
- Device: X200U
- Customer: 买家昵称
- Date: 2026-05-20 ~ 2026-05-25
[View details] [Ignore & Continue]
```

### 8. DateTime Pickers on Mobile
Element Plus `VueDatePicker` may not work well on mobile. Consider:
- Native `<input type="date" />`
- Or third-party mobile-friendly picker like `vant` or `mint-ui`

---

## File Dependencies & Imports

### BookingDialog.vue uses:
```typescript
import { useGanttStore } from '@/stores/gantt'
import { useDeviceManagement } from '@/composables/useDeviceManagement'
import { useAvailabilityCheck } from '@/composables/useAvailabilityCheck'
import { useConflictDetection } from '@/composables/useConflictDetection'
import { getCreateRentalRules } from '@/composables/useRentalFormValidation'
import { extractPhoneNumber } from '@/utils/phoneExtractor'
import axios from 'axios'
import dayjs from 'dayjs'
import VueDatePicker from '@vuepic/vue-datepicker'
import { ElMessage, ElMessageBox, type FormInstance } from 'element-plus'
```

### EditRentalDialogNew.vue uses:
```typescript
import { useGanttStore } from '@/stores/gantt'
import { useDeviceManagement } from '@/composables/useDeviceManagement'
import { useAvailabilityCheck } from '@/composables/useAvailabilityCheck'
import { useConflictDetection } from '@/composables/useConflictDetection'
import { getEditRentalRules } from '@/composables/useRentalFormValidation'
import dayjs from 'dayjs'
import VueDatePicker from '@vuepic/vue-datepicker'
```

### Sub-components (shared):
- `RentalBasicForm.vue` - Section 1 fields, handles order fetch
- `RentalShippingForm.vue` - Shipping/status fields, destination → phone extraction watch
- `RentalAccessorySelector.vue` - Accessories section with filtering logic
- `RentalActionButtons.vue` - Top action buttons (EDIT mode only)

---

## Validation Rules & Error Handling

### Required Fields
**CREATE**:
- startDate, endDate, logisticsDays, customerName
- Optional but with regex if filled: customerPhone
- Optional: everything else

**EDIT**:
- deviceId, endDate
- Optional but with regex if filled: customerPhone
- Optional: everything else

### Validation Triggers
- `trigger: 'change'` - Validates on field change
- `trigger: 'blur'` - Validates on field blur

### Form Validation
Both modes use `formRef.value?.validate()` which returns Promise:
```typescript
try {
  await formRef.value?.validate()
  // Passed, continue submission
} catch {
  // Failed, stop here
  return
}
```

---

## Architecture Insights for Mobile

### 1. Shared Component Pattern
Both CREATE and EDIT reuse same sub-components:
- RentalBasicForm (renamed fields)
- RentalShippingForm (shared)
- RentalAccessorySelector (shared)

Mobile benefit: Can refactor sub-components once, improves both modes.

### 2. Composable Pattern
- `useDeviceManagement()` - Loads and manages devices/accessories
- `useAvailabilityCheck()` - Tracks availability state
- `useConflictDetection()` - Checks conflicts
- `useRentalFormValidation()` - Provides validation rules

Mobile benefit: Can create mobile-specific composables (e.g., `useMobileDeviceManagement`) without touching components.

### 3. Store Pattern (Pinia)
- `ganttStore.createRental(data)`
- `ganttStore.updateRental(id, data)`
- `ganttStore.deleteRental(id)`
- `ganttStore.findAvailableSlot(...)`
- `ganttStore.fetchXianyuOrder(...)`

Mobile benefit: All API calls are isolated in store, easy to mock/test.

### 4. State Management
- **Form state**: Managed in component refs (reactive)
- **UI state**: Loading flags (submitting, searching, fetchingOrder)
- **Availability state**: Managed in composables (checked, availableItems, unavailableItems)

Mobile challenge: Many refs to manage, state sprawl. Could benefit from Pinia form store.

---

## Quick Complexity Checklist for Mobile Developers

- [ ] **14 form fields** (CREATE) vs 13 (EDIT) - need careful grouping
- [ ] **3 async operations** - need loading indicators + error handling
- [ ] **Phone extraction watch** - can auto-fill customerPhone
- [ ] **Order fetch chain** - can auto-fill 5 fields
- [ ] **Device conflict check** - shows dialog if conflict
- [ ] **Duplicate detection** - shows dialog with list (CREATE only)
- [ ] **Data transformation** - UI ↔ API format conversion
- [ ] **Validation rules** - Different for CREATE vs EDIT
- [ ] **Accessory matching** - Brittle string matching logic
- [ ] **DateTime pickers** - VueDatePicker may not be mobile-friendly
- [ ] **Conditional visibility** - Several fields show/hide based on state
- [ ] **Disabled fields** - Some fields are read-only (customer_name, start_date, buyerId)

---

## Next Steps for Mobile Implementation

1. **Audit VueDatePicker on Mobile**: Test responsiveness and UX
2. **Create Mobile Sub-Components**: Adapt RentalBasicForm, RentalShippingForm, RentalAccessorySelector for mobile
3. **Design Multi-Step Form**: Consider breaking into 3-4 steps instead of one long form
4. **Implement Collapsible Sections**: Hide non-essential fields by default
5. **Add Auto-Fill Indicators**: Highlight fields that were auto-filled
6. **Improve Async Feedback**: Add clear loading messages, not just spinners
7. **Test on Real Devices**: iOS Safari, Android Chrome with slow 3G network
8. **Consider Native Mobile App**: If web version becomes too complex, might warrant native approach

