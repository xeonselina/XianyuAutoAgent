# Form Field Mapping & Data Transformation Reference

**For Mobile Form Implementation**

---

## CREATE Mode Field Mapping

### Database/API ↔ UI Format

| UI Field Name | Type | API Field Name | Default | Required | Notes |
|---|---|---|---|---|---|
| startDate | Date | start_date | null | ✅ | Format: YYYY-MM-DD |
| endDate | Date | end_date | null | ✅ | Min: startDate, Format: YYYY-MM-DD |
| logisticsDays | number | (calculated) | 1 | ✅ | Range: 0-7 |
| xianyuOrderNo | string | xianyu_order_no | '' | ❌ | Optional, triggers auto-fetch |
| selectedDeviceId | number | device_id | null | ✅ | Required for submit |
| customerName | string | customer_name | '' | ✅ | Xianyu ID (auto-fill from order) |
| customerPhone | string | customer_phone | '' | ❌ | Regex: /^1[3-9]\d{9}$/, auto-extract from destination |
| destination | string | destination | '' | ❌ | Textarea 3 rows, triggers phone extraction |
| orderAmount | string | order_amount | '' | ❌ | Number input (store as float, divide by 100 on fetch) |
| buyerId | string | buyer_id | '' | ❌ | Disabled/read-only (auto-fill from order) |
| bundledAccessories | Array['handle' \| 'lens_mount'] | includes_handle, includes_lens_mount | [] | ❌ | Checkbox group |
| photoTransfer | boolean | photo_transfer | false | ❌ | Single checkbox |
| phoneHolderId | number \| null | accessories (array) | null | ❌ | Select dropdown, library/inventory item |
| tripodId | number \| null | accessories (array) | null | ❌ | Select dropdown, library/inventory item |

### Submission Data Structure

**POST /api/rentals (create)**

```typescript
{
  device_id: number,
  start_date: "YYYY-MM-DD",
  end_date: "YYYY-MM-DD",
  customer_name: string,
  customer_phone: string,
  destination: string,
  ship_out_time: "YYYY-MM-DD HH:mm:ss",  // Calculated from startDate - logisticsDays
  ship_in_time: "YYYY-MM-DD HH:mm:ss",    // Calculated from endDate + logisticsDays
  includes_handle: boolean,                // from bundledAccessories
  includes_lens_mount: boolean,            // from bundledAccessories
  accessories: number[],                  // [phoneHolderId, tripodId].filter(id => id !== null)
  xianyu_order_no: string,
  order_amount: number,                   // parseFloat(orderAmount)
  buyer_id: string,
  photo_transfer: boolean
}
```

### Calculation Logic

```typescript
// shipOutTime calculation
const shipOutTime = availableSlot 
  ? availableSlot.shipOutDate
  : dayjs(form.value.startDate)
    .startOf('day')
    .subtract(1 + form.value.logisticsDays, 'day')
    .toDate()

// shipInTime calculation
const shipInTime = availableSlot 
  ? availableSlot.shipInDate
  : dayjs(form.value.endDate)
    .startOf('day')
    .add(1 + form.value.logisticsDays, 'day')
    .toDate()
```

### Auto-Fill Chains

#### Order Fetch Auto-Fill
```
POST /api/rentals/fetch-xianyu-order { order_no: string }

Response Fields              → UI Field
response.buyer_nick          → customerName
response.receiver_mobile     → customerPhone (overwrites)
response.receiver_name +     
  response.receiver_mobile +
  address parts              → destination

response.buyer_eid           → buyerId
response.pay_amount / 100    → orderAmount
```

#### Phone Extraction from Destination
```
watch(() => form.value.destination, (newDestination) => {
  if (newDestination && !form.value.customerPhone) {
    const phone = extractPhoneNumber(newDestination)  // regex: /^1[3-9]\d{9}$/
    if (phone) {
      form.value.customerPhone = phone
    }
  }
})
```

---

## EDIT Mode Field Mapping

### Database/API ↔ UI Format

| UI Field Name | Type | API Field Name | Default | Required | Notes |
|---|---|---|---|---|---|
| deviceId | number | device_id | 0 | ✅ | Select dropdown, triggers conflict check |
| endDate | Date | end_date | null | ✅ | Min: rental.start_date |
| customerPhone | string | customer_phone | '' | ❌ | Regex: /^1[3-9]\d{9}$/ |
| destination | string | destination | '' | ❌ | Textarea, triggers phone extraction |
| shipOutTrackingNo | string | ship_out_tracking_no | '' | ❌ | Optional tracking number |
| shipInTrackingNo | string | ship_in_tracking_no | '' | ❌ | Optional tracking number |
| shipOutTime | Date | ship_out_time | null | ❌ | DateTime picker |
| shipInTime | Date | ship_in_time | null | ❌ | DateTime picker |
| status | string | status | 'not_shipped' | ❌ | Select: not_shipped/shipped/returned/completed/cancelled |
| bundledAccessories | Array['handle' \| 'lens_mount'] | includes_handle, includes_lens_mount | [] | ❌ | Checkbox group |
| photoTransfer | boolean | photo_transfer | false | ❌ | Single checkbox |
| phoneHolderId | number \| null | accessories (array) | null | ❌ | Select dropdown |
| tripodId | number \| null | accessories (array) | null | ❌ | Select dropdown |
| xianyuOrderNo | string | xianyu_order_no | '' | ❌ | Text input + fetch button |
| orderAmount | string | order_amount | '' | ❌ | Number input (read-only but editable) |
| (customer_name) | string | customer_name | '' | ❌ | **Display-only/disabled** |
| (start_date) | Date | start_date | null | ❌ | **Display-only/disabled** |
| (buyerId) | string | buyer_id | '' | ❌ | **Display-only/disabled** |

### Submission Data Structure

**PUT /api/rentals/:id (update)**

```typescript
{
  device_id: number,
  end_date: "YYYY-MM-DD",
  customer_phone: string,
  destination: string,
  ship_out_tracking_no: string,
  ship_in_tracking_no: string,
  ship_out_time: "YYYY-MM-DD HH:mm:ss" | null,
  ship_in_time: "YYYY-MM-DD HH:mm:ss" | null,
  status: string,
  includes_handle: boolean,
  includes_lens_mount: boolean,
  accessories: number[],                  // [phoneHolderId, tripodId].filter(id => id !== null)
  xianyu_order_no: string,
  order_amount: number,                   // parseFloat(orderAmount) if not empty
  buyer_id: string,
  photo_transfer: boolean
}
```

### Data Loading & Transformation (initForm)

```typescript
const initForm = async () => {
  // Load latest rental data
  const latestRental = await ganttStore.getRentalById(props.rental.id)
  const rentalData = latestRental || props.rental

  // Transform API → UI format
  
  // 1. Bundled accessories (booleans → array of strings)
  const bundledAccessories: ('handle' | 'lens_mount')[] = []
  if (rentalData.includes_handle) {
    bundledAccessories.push('handle')
  }
  if (rentalData.includes_lens_mount) {
    bundledAccessories.push('lens_mount')
  }

  // 2. Inventory accessories (find specific items)
  const accessories = rentalData.accessories || []
  
  const phoneHolder = accessories.find((a: any) => 
    a.type === 'phone_holder' || 
    a.name?.includes('手机支架') || 
    a.name?.toLowerCase().includes('phone') ||
    a.model?.includes('手机支架') ||
    a.model?.toLowerCase().includes('phone')
  )
  
  const tripod = accessories.find((a: any) => 
    a.type === 'tripod' || 
    a.name?.includes('三脚架') || 
    a.name?.toLowerCase().includes('tripod') ||
    a.model?.includes('三脚架') ||
    a.model?.toLowerCase().includes('tripod')
  )

  // 3. Initialize form
  form.value = {
    deviceId: rentalData.device_id,
    endDate: new Date(rentalData.end_date),
    customerPhone: rentalData.customer_phone || '',
    destination: rentalData.destination || '',
    shipOutTrackingNo: rentalData.ship_out_tracking_no || '',
    shipInTrackingNo: rentalData.ship_in_tracking_no || '',
    shipOutTime: rentalData.ship_out_time ? new Date(rentalData.ship_out_time) : null,
    shipInTime: rentalData.ship_in_time ? new Date(rentalData.ship_in_time) : null,
    status: rentalData.status || 'not_shipped',
    bundledAccessories,
    phoneHolderId: phoneHolder?.id || null,
    tripodId: tripod?.id || null,
    xianyuOrderNo: rentalData.xianyu_order_no || '',
    orderAmount: rentalData.order_amount ? String(rentalData.order_amount) : '',
    buyerId: rentalData.buyer_id || '',
    photoTransfer: rentalData.photo_transfer || false
  }
}
```

### Conflict Detection

```typescript
// Triggered when user changes device
const handleDeviceChange = async (deviceId: number) => {
  if (!props.rental) return

  const selectedDevice = deviceManagement.devices.value.find(d => d.id === deviceId)
  if (!selectedDevice) return

  // Use ship_out_time if available, else start_date
  const shipOutTime = props.rental.ship_out_time || props.rental.start_date
  const shipInTime = props.rental.ship_in_time || props.rental.end_date

  const hasConflict = await conflictDetection.checkDeviceConflict({
    deviceId,
    startDate: shipOutTime,
    endDate: shipInTime,
    excludeRentalId: props.rental.id  // Don't check against self
  })

  if (hasConflict) {
    // Show confirmation dialog
    try {
      await ElMessageBox.confirm(
        `设备 "${selectedDevice.name}" 在该时间段有冲突，确定要选择吗？`,
        '设备冲突警告',
        {
          confirmButtonText: '确定选择',
          cancelButtonText: '取消',
          type: 'warning'
        }
      )
    } catch {
      // User clicked cancel, revert deviceId
      form.value.deviceId = props.rental.device_id
    }
  }
}
```

---

## Accessory Type Detection

**Current Logic (Brittle String Matching)**

```typescript
// Phone holder detection
const isPhoneHolder = (accessory: any) => 
  accessory.name.includes('手机支架') || 
  accessory.name.toLowerCase().includes('phone') ||
  (accessory.model && (
    accessory.model.includes('手机支架') || 
    accessory.model.toLowerCase().includes('phone')
  ))

// Tripod detection
const isTripod = (accessory: any) => 
  accessory.name.includes('三脚架') || 
  accessory.name.toLowerCase().includes('tripod') ||
  (accessory.model && (
    accessory.model.includes('三脚架') || 
    accessory.model.toLowerCase().includes('tripod')
  ))

// Handle detection
const isHandle = (accessory: any) =>
  accessory.model?.includes('手柄')  // Only checks model
```

**Recommended Backend Approach**

```typescript
interface Accessory {
  id: number
  name: string
  model: string
  type: 'phone_holder' | 'tripod' | 'handle' | 'lens_mount' | 'other'  // Add this field
  // ... other fields
}
```

---

## Validation Rules

### CREATE Mode (getCreateRentalRules)

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
    { pattern: /^1[3-9]\d{9}$/, message: '请输入正确的手机号码', trigger: 'blur' }
  ],
  destination: [
    // No validation rule
  ]
}
```

### EDIT Mode (getEditRentalRules)

```typescript
{
  deviceId: [
    { required: true, message: '请选择设备', trigger: 'change' }
  ],
  endDate: [
    { required: true, message: '请选择结束日期', trigger: 'change' }
  ],
  customerPhone: [
    { pattern: /^1[3-9]\d{9}$/, message: '请输入正确的手机号码', trigger: 'blur' }
  ]
  // No validation on other fields
}
```

### Phone Number Validation

```typescript
const validatePhone = (phone: string): boolean => {
  const phoneRegex = /^1[3-9]\d{9}$/
  return phoneRegex.test(phone)
}
```

---

## Status Enum Values

```typescript
type RentalStatus = 
  | 'not_shipped'    // 未发货
  | 'shipped'        // 已发货
  | 'returned'       // 已收回
  | 'completed'      // 已完成
  | 'cancelled'      // 已取消

// Select options:
[
  { label: '未发货', value: 'not_shipped' },
  { label: '已发货', value: 'shipped' },
  { label: '已收回', value: 'returned' },
  { label: '已完成', value: 'completed' },
  { label: '已取消', value: 'cancelled' }
]
```

---

## Action Buttons (EDIT Mode Only)

```typescript
interface RentalActionButtons {
  [租赁合同]: () => {
    const url = router.resolve({ path: `/contract/${props.rental.id}` })
    window.open(url.href, '_blank')
  },
  
  [发货单]: () => {
    const url = router.resolve({ path: `/shipping/${props.rental.id}` })
    window.open(url.href, '_blank')
  },
  
  [发货到闲鱼]: async () => {
    // Conditions: xianyu_order_no && ship_out_tracking_no must exist
    await ganttStore.shipRentalToXianyu(props.rental.id)
    // Reload latest data
  },
  
  [删除租赁]: async () => {
    // Show confirmation dialog
    await ElMessageBox.confirm('确定要删除这条租赁记录吗？此操作不可撤销。')
    // Call: ganttStore.deleteRental(props.rental.id)
  }
}
```

---

## API Endpoints Summary

| Endpoint | Method | Use Case | Request | Response |
|---|---|---|---|---|
| /api/rentals | POST | Create new rental (CREATE) | rentalData object | `{ success, data: rental }` |
| /api/rentals/:id | PUT | Update rental (EDIT) | updateData object | `{ success, data: rental }` |
| /api/rentals/:id | DELETE | Delete rental | (none) | `{ success }` |
| /api/rentals/:id | GET | Get rental by ID | (none) | `{ success, data: rental }` |
| /api/rentals/fetch-xianyu-order | POST | Fetch Xianyu order info | `{ order_no: string }` | `{ success, data: orderData }` |
| ganttStore.findAvailableSlot | (store method) | Find available devices | dates, logistics | `{ device, shipOutDate, shipInDate }` |
| ganttStore.checkDeviceConflict | (store method) | Check device conflict | deviceId, dates | `hasConflict: boolean` |
| ganttStore.shipRentalToXianyu | (store method) | Ship to Xianyu | rentalId | `{ success }` |

---

## Mobile Implementation Checklist

- [ ] Identify breaking points for sectioned layout
- [ ] Test VueDatePicker responsiveness on mobile
- [ ] Implement auto-fill highlighting for order fetch
- [ ] Add loading banners for async operations
- [ ] Handle slow network (3G) gracefully
- [ ] Test keyboard handling on iOS/Android
- [ ] Implement collapsible sections for optional fields
- [ ] Add inline error messaging (not just validation)
- [ ] Test phone number extraction with various formats
- [ ] Verify datetime picker works on mobile
- [ ] Test accessory filtering with long lists
- [ ] Implement fallback for unsupported features
- [ ] Add offline detection + error messaging
- [ ] Test form submission with intermittent network
- [ ] Verify back button behavior closes form correctly

