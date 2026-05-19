# Rental Form Components - Complete Analysis

## Overview
The rental system has **two main creation/editing flows**:
1. **BookingDialog.vue** - Create NEW rental (600px width dialog)
2. **EditRentalDialogNew.vue** - Edit EXISTING rental (500px width dialog)

The forms are composed of **3 sub-components**:
- **RentalBasicForm.vue** - Device + dates + Xianyu order info
- **RentalShippingForm.vue** - Customer contact + tracking + status
- **RentalAccessorySelector.vue** - Bundled & inventory accessories

---

## FILE PATHS

```
/Users/jimmypan/git_repo/XianyuAutoAgent/InventoryManager/frontend/src/
├── components/rental/
│   ├── BookingDialog.vue                    [CREATE - 302 lines]
│   ├── EditRentalDialogNew.vue              [EDIT - 580 lines]
│   ├── RentalBasicForm.vue                  [SHARED - 238 lines]
│   ├── RentalShippingForm.vue               [SHARED - 186 lines]
│   └── RentalAccessorySelector.vue          [SHARED - 309 lines]
├── composables/
│   ├── useRentalFormValidation.ts           [Validation rules]
│   ├── useAvailabilityCheck.ts              [Availability logic]
│   ├── useConflictDetection.ts              [Conflict detection]
│   └── useDeviceManagement.ts               [Device/accessory loading]
```

---

## FORM FIELD SUMMARY (All Fields)

### Basic Fields
| Label | Prop | Type | Create | Edit | Required | Conditional |
|-------|------|------|--------|------|----------|-------------|
| 开始日期 (Start Date) | startDate | Date | ✓ | ✗ | ✓ | No |
| 结束日期 (End Date) | endDate | Date | ✓ | ✓ | ✓ | No |
| 物流天数 (Logistics Days) | logisticsDays | Number | ✓ | ✗ | ✓ | No |
| 闲鱼订单号 (Xianyu Order No) | xianyuOrderNo | String | ✓ | ✓ | ✗ | No |
| 订单金额 (Order Amount) | orderAmount | Number | ✓ | ✓ | ✗ | No |
| 买家ID (Buyer ID) | buyerId | String | ✓ | ✓ | ✗ | disabled |
| 设备名称 (Device Name) | deviceId | Number | ✓ | ✓ | ✓ | No |
| 闲鱼ID (Customer Name) | customerName | String | ✓ | ✗ | ✓ | No |
| 客户电话 (Customer Phone) | customerPhone | String | ✓ | ✓ | ✗ | Watch-dependent |
| 收件信息 (Destination) | destination | String | ✓ | ✓ | ✗ | Watch-dependent |

### Shipping & Status Fields
| Label | Prop | Type | Create | Edit | Required | Conditional |
|-------|------|------|--------|------|----------|-------------|
| 寄出运单号 (Ship Out Tracking) | shipOutTrackingNo | String | ✓ | ✓ | ✗ | Button disabled if empty |
| 寄回运单号 (Ship In Tracking) | shipInTrackingNo | String | ✓ | ✓ | ✗ | Button disabled if empty |
| 寄出时间 (Ship Out Time) | shipOutTime | DateTime | ✓ | ✓ | ✗ | No |
| 收回时间 (Ship In Time) | shipInTime | DateTime | ✓ | ✓ | ✗ | No |
| 租赁状态 (Status) | status | Select | ✓ | ✓ | ✓ | Enum |

### Accessory Fields
| Label | Prop | Type | Create | Edit | Required | Conditional |
|-------|------|------|--------|------|----------|-------------|
| 配套附件 (Bundled) | bundledAccessories | Array | ✓ | ✓ | ✗ | Checkbox group |
| 代传照片 (Photo Transfer) | photoTransfer | Boolean | ✓ | ✓ | ✗ | Single checkbox |
| 手机支架 (Phone Holder) | phoneHolderId | Number | ✓ | ✓ | ✗ | Optional select |
| 三脚架 (Tripod) | tripodId | Number | ✓ | ✓ | ✗ | Optional select |

---

## ACTUAL FORM STATE OBJECTS

### BookingDialog.vue (Create)
```javascript
// Line 347-363
const form = ref({
  startDate: null as Date | null,
  endDate: null as Date | null,
  logisticsDays: 1,
  selectedDeviceId: null as number | null,
  customerName: '',
  customerPhone: '',
  destination: '',
  // 新：分离配套附件和库存附件
  bundledAccessories: [] as ('handle' | 'lens_mount')[],
  phoneHolderId: null as number | null,
  tripodId: null as number | null,
  xianyuOrderNo: '',
  orderAmount: '',
  buyerId: '',
  photoTransfer: false  // 代传照片标记
})
```

### EditRentalDialogNew.vue (Edit)
```javascript
// Line 140-160
const form = ref({
  deviceId: 0,
  endDate: null as Date | null,
  customerPhone: '',
  destination: '',
  shipOutTrackingNo: '',
  shipInTrackingNo: '',
  shipOutTime: null as Date | null,
  shipInTime: null as Date | null,
  status: 'not_shipped',
  // 新：分离配套附件和库存附件
  bundledAccessories: [] as ('handle' | 'lens_mount')[],
  phoneHolderId: null as number | null,
  tripodId: null as number | null,
  // 保留accessories为了兼容性（用于RentalAccessorySelector）
  accessories: [] as number[],
  xianyuOrderNo: '',
  orderAmount: '',
  buyerId: '',
  photoTransfer: false  // 代传照片标记
})
```

---

## VALIDATION RULES

### Create Rental Rules (getCreateRentalRules)
```javascript
// src/composables/useRentalFormValidation.ts (Lines 10-31)
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
    // 收件信息改为非必填
  ]
}
```

### Edit Rental Rules (getEditRentalRules)
```javascript
// src/composables/useRentalFormValidation.ts (Lines 36-48)
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
}
```

---

## WATCH LOGIC & AUTO-FILL

### Watch: destination → customerPhone (Both Forms)
**Location**: RentalShippingForm.vue (Lines 161-171) & BookingDialog.vue (Lines 821-831)

```typescript
watch(() => form.value.destination, (newDestination) => {
  // 只有当客户电话为空时才自动提取
  if (newDestination && !form.value.customerPhone) {
    const extractedPhone = extractPhoneNumber(newDestination)
    if (extractedPhone) {
      form.value.customerPhone = extractedPhone
      ElMessage.success('已自动从收件信息中提取手机号')
    }
  }
})
```

**Purpose**: Auto-extract phone number from destination field using regex.
**Trigger**: Only when destination changes AND customerPhone is empty
**Uses**: `extractPhoneNumber()` utility function

### Watch: startDate change (BookingDialog)
**Location**: BookingDialog.vue (Lines 419-433)

```typescript
const handleStartDateChange = (date: Date | null) => {
  form.value.startDate = date
  if (date && form.value.endDate && dayjs(form.value.endDate).isBefore(dayjs(date))) {
    form.value.endDate = null  // Clear endDate if it becomes invalid
  }

  availableSlot.value = null
  availability.resetAll()

  if (date && form.value.endDate) {
    nextTick(() => {
      checkAvailabilities()  // Re-check device/accessory availability
    })
  }
}
```

**Purpose**: Validate date range, reset availability checks when dates change
**Side Effects**: Clears availability state, resets slots

### Watch: endDate change (BookingDialog)
**Location**: BookingDialog.vue (Lines 435-445)

```typescript
const handleEndDateChange = (date: Date | null) => {
  form.value.endDate = date
  availableSlot.value = null
  availability.resetAll()

  if (date && form.value.startDate) {
    nextTick(() => {
      checkAvailabilities()
    })
  }
}
```

### Watch: Dialog open → Initialize form (EditRentalDialogNew)
**Location**: EditRentalDialogNew.vue (Lines 536-553)

```typescript
watch(
  () => props.rental,
  () => {
    if (props.rental) {
      initForm()
    }
  },
  { immediate: true }
)

watch(
  () => props.modelValue,
  (newValue) => {
    if (newValue && props.rental) {
      initForm()
    }
  }
)
```

**Purpose**: Load rental data when dialog opens
**Calls**: `initForm()` which loads latest rental data and populates form

### initForm() - Data Mapping (EditRentalDialogNew)
**Location**: EditRentalDialogNew.vue (Lines 463-533)

```typescript
const initForm = async () => {
  if (props.rental) {
    deviceConflictChecked.value = false
    accessoryConflictChecked.value = false

    const latestRental = await loadLatestRentalData()
    const rentalData = latestRental || props.rental

    // 从 API 响应转换为 UI 格式
    const bundledAccessories: ('handle' | 'lens_mount')[] = []
    if (rentalData.includes_handle) {
      bundledAccessories.push('handle')
    }
    if (rentalData.includes_lens_mount) {
      bundledAccessories.push('lens_mount')
    }

    // 从 accessories数组中提取库存附件
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

    // 也从 child_rentals中提取（兼容旧数据）
    const childAccessoryIds = (rentalData.child_rentals || [])
      .map((child: any) => child.device_id)
      .filter(Boolean)

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
      // 新字段
      bundledAccessories,
      phoneHolderId: phoneHolder?.id || null,
      tripodId: tripod?.id || null,
      // 兼容字段（用于RentalAccessorySelector）
      accessories: childAccessoryIds,
      xianyuOrderNo: rentalData.xianyu_order_no || '',
      orderAmount: rentalData.order_amount ? String(rentalData.order_amount) : '',
      buyerId: rentalData.buyer_id || '',
      photoTransfer: rentalData.photo_transfer || false
    }

    if (latestRental) {
      Object.assign(props.rental, latestRental)
    }

    await Promise.all([
      deviceManagement.loadDevices(),
      deviceManagement.loadAccessories()
    ])
  }
}
```

---

## CONDITIONAL LOGIC & V-IF / V-SHOW

### RentalBasicForm.vue

**Device Selection (Lines 4-31)**
```html
<el-form-item label="设备名称" prop="deviceId">
  <el-select
    v-model="form.deviceId"
    placeholder="选择设备"
    @change="handleDeviceChange"
    @focus="handleDeviceSelectorFocus"
    :loading="loadingDevices"
  >
    <el-option
      v-for="device in availableDevices"
      :key="device.id"
      :label="`${device.name} (${device.serial_number || '无序列号'})`"
      :value="device.id"
    >
      <div style="display: flex; justify-content: space-between; align-items: center;">
        <span>{{ device.name }}</span>
        <div style="font-size: 12px; color: #999; display: flex; align-items: center; gap: 8px;">
          <span v-if="device.serial_number">{{ device.serial_number }}</span>
          <el-tag v-if="device.conflicted" type="danger" size="small" effect="dark">
            时间冲突
          </el-tag>
        </div>
      </div>
    </el-option>
  </el-select>
</el-form-item>
```

**Conditional Display**: 
- `v-if="device.serial_number"` - Only show serial if present
- `v-if="device.conflicted"` - Show "时间冲突" tag if device has conflict

### RentalAccessorySelector.vue

**Already Selected Accessories Summary (Lines 103-160)**
```html
<div v-if="hasSelectedAccessories" class="selected-accessories">
  <h4>已选择的附件:</h4>
  <div class="accessory-list">
    <!-- 配套附件 -->
    <div v-if="form.bundledAccessories.includes('handle')" class="accessory-item bundled">
      <div class="accessory-info">
        <strong>手柄</strong>
        <span class="accessory-model">(配套附件)</span>
      </div>
      <el-tag type="success" size="small">配套</el-tag>
    </div>
    <div v-if="form.bundledAccessories.includes('lens_mount')" class="accessory-item bundled">
      <div class="accessory-info">
        <strong>镜头支架</strong>
        <span class="accessory-model">(配套附件)</span>
      </div>
      <el-tag type="success" size="small">配套</el-tag>
    </div>
    
    <!-- 库存附件 -->
    <div v-if="selectedPhoneHolder" class="accessory-item inventory">
      <div class="accessory-info">
        <strong>{{ selectedPhoneHolder.name }}</strong>
        <span class="accessory-model">{{ selectedPhoneHolder.model }}</span>
      </div>
      <div style="display: flex; gap: 8px; align-items: center">
        <el-tag type="info" size="small">库存</el-tag>
        <el-button
          type="danger"
          size="small"
          @click="form.phoneHolderId = null; handleInventoryAccessoryChange()"
          text
        >
          <el-icon><Delete /></el-icon>
          移除
        </el-button>
      </div>
    </div>
    <div v-if="selectedTripod" class="accessory-item inventory">
      <div class="accessory-info">
        <strong>{{ selectedTripod.name }}</strong>
        <span class="accessory-model">{{ selectedTripod.model }}</span>
      </div>
      <div style="display: flex; gap: 8px; align-items: center">
        <el-tag type="info" size="small">库存</el-tag>
        <el-button
          type="danger"
          size="small"
          @click="form.tripodId = null; handleInventoryAccessoryChange()"
          text
        >
          <el-icon><Delete /></el-icon>
          移除
        </el-button>
      </div>
    </div>
  </div>
</div>
```

**Computed Helper**:
```typescript
// Line 223-227
const hasSelectedAccessories = computed(() => {
  return props.form.bundledAccessories.length > 0 || 
         props.form.phoneHolderId !== null || 
         props.form.tripodId !== null
})
```

**Conditional Display**:
- `v-if="hasSelectedAccessories"` - Show summary section ONLY if any accessory selected
- `v-if="form.bundledAccessories.includes('handle')"` - Show handle item
- `v-if="form.bundledAccessories.includes('lens_mount')"` - Show lens mount item
- `v-if="selectedPhoneHolder"` - Show phone holder summary
- `v-if="selectedTripod"` - Show tripod summary

### BookingDialog.vue

**Available Slot Display (Lines 277-286)**
```html
<div v-if="availableSlot" class="slot-info">
  <div class="slot-device">
    <el-icon><Monitor /></el-icon>
    已找到可用设备: {{ availableSlot.device?.name || '未知设备' }}
  </div>
  <div class="slot-times">
    <div>寄出时间: {{ formatDateTime(availableSlot.shipOutDate) }}</div>
    <div>收回时间: {{ formatDateTime(availableSlot.shipInDate) }}</div>
  </div>
</div>
```

**Accessory Filter Selects (Lines 191-274)**
```html
<!-- 库存附件 - 手机支架 -->
<el-form-item label="手机支架">
  <el-select 
    v-model="form.phoneHolderId" 
    placeholder="选择手机支架(可选)" 
    :loading="loadingAccessories"
    @focus="handleAccessoryFocus"
  >
    <el-option
      v-for="holder in phoneHolders"
      :key="holder.id"
      :label="holder.name"
      :value="holder.id"
      :disabled="availability.accessoryAvailability.value.checked && !availability.isAccessoryAvailable(holder.id)"
    >
      ...display logic...
    </el-option>
  </el-select>
</el-form-item>
```

**Filter Computed**:
```typescript
// Lines 381-395
const phoneHolders = computed(() => {
  return deviceManagement.accessories.value.filter(a => 
    a.name.includes('手机支架') || a.name.toLowerCase().includes('phone') ||
    (a.model && (a.model.includes('手机支架') || a.model.toLowerCase().includes('phone')))
  )
})

const tripods = computed(() => {
  return deviceManagement.accessories.value.filter(a => 
    a.name.includes('三脚架') || a.name.toLowerCase().includes('tripod') ||
    (a.model && (a.model.includes('三脚架') || a.model.toLowerCase().includes('tripod')))
  )
})
```

**Disabled Logic**:
```html
:disabled="availability.accessoryAvailability.value.checked && !availability.isAccessoryAvailable(holder.id)"
```
- Disabled ONLY if: availability has been checked AND accessory is NOT available

---

## COMPUTED PROPERTIES

### BookingDialog.vue
```typescript
// Line 377-379
const canSearchSlot = computed(() => {
  return form.value.startDate && form.value.endDate && form.value.logisticsDays >= 0
})
```

### RentalAccessorySelector.vue
```typescript
// Lines 195-227
const phoneHolders = computed(() => {...filter phone holders...})
const tripods = computed(() => {...filter tripods...})
const selectedPhoneHolder = computed(() => {
  if (!props.form.phoneHolderId) return null
  return props.availableControllers.find(a => a.id === props.form.phoneHolderId)
})
const selectedTripod = computed(() => {
  if (!props.form.tripodId) return null
  return props.availableControllers.find(a => a.id === props.form.tripodId)
})
const hasSelectedAccessories = computed(() => {
  return props.form.bundledAccessories.length > 0 || 
         props.form.phoneHolderId !== null || 
         props.form.tripodId !== null
})
```

### EditRentalDialogNew.vue
```typescript
// Line 176-179
const minSelectableDate = computed(() => {
  if (!props.rental) return null
  return new Date(props.rental.start_date)
})
```

---

## API ENDPOINT: XIANYU ORDER FETCH

**Endpoint**: `POST /api/rentals/fetch-xianyu-order`

**Request Payload**:
```javascript
{
  order_no: string  // 订单号 from form.xianyuOrderNo
}
```

**Response**:
```javascript
{
  success: boolean,
  data: {
    receiver_name: string,
    receiver_mobile: string,
    prov_name: string,
    city_name: string,
    area_name: string,
    town_name: string,
    address: string,
    buyer_eid: string,
    buyer_nick: string,
    pay_amount: number (in cents, not yuan)
  },
  message: string
}
```

**Auto-fill Logic** (RentalBasicForm.vue, Lines 143-229 & BookingDialog.vue, Lines 601-693):
```typescript
const handleFetchOrderInfo = async () => {
  const orderNo = props.form.xianyuOrderNo?.trim()

  if (!orderNo) {
    ElMessage.warning('请先输入订单号')
    return
  }

  fetchingOrder.value = true

  try {
    const response = await axios.post('/api/rentals/fetch-xianyu-order', {
      order_no: orderNo
    })

    if (response.data.success && response.data.data) {
      const orderData = response.data.data

      // 组合收件信息：姓名 + 电话 + 地址
      const destinationParts = []

      // 添加收件人姓名
      if (orderData.receiver_name) {
        destinationParts.push(orderData.receiver_name)
      }

      // 添加收件人电话
      if (orderData.receiver_mobile) {
        destinationParts.push(orderData.receiver_mobile)
      }

      // 添加完整地址
      const addressParts = [
        orderData.prov_name,
        orderData.city_name,
        orderData.area_name,
        orderData.town_name,
        orderData.address
      ].filter(Boolean)

      if (addressParts.length > 0) {
        destinationParts.push(addressParts.join(''))
      }

      if (destinationParts.length > 0) {
        props.form.destination = destinationParts.join(' ')
      }

      // 自动填充买家ID
      if (orderData.buyer_eid) {
        props.form.buyerId = orderData.buyer_eid
      }

      // 自动填充订单金额（从分转换为元）
      if (orderData.pay_amount) {
        props.form.orderAmount = (orderData.pay_amount / 100).toFixed(2)
      }

      // 最后填充手机号（覆盖可能被watch自动提取的手机号）
      if (orderData.receiver_mobile) {
        props.form.customerPhone = orderData.receiver_mobile
      }

      // 在CREATE表单中，自动填充闲鱼ID
      // if (orderData.buyer_nick) {
      //   form.value.customerName = orderData.buyer_nick
      // }

      ElMessage.success('订单信息获取成功')
    } else {
      ElMessage.error(response.data.message || '获取订单信息失败')
    }
  } catch (error: any) {
    ElMessage.error(error.response?.data?.message || '获取订单信息失败，请检查订单号是否正确')
  } finally {
    fetchingOrder.value = false
  }
}
```

**Auto-fill Fields**:
- `destination` = receiver_name + receiver_mobile + full address (joined with space)
- `buyerId` = buyer_eid
- `orderAmount` = pay_amount / 100 (convert from cents to yuan)
- `customerPhone` = receiver_mobile (LAST, overrides watch-extracted)
- `customerName` = buyer_nick (CREATE ONLY, if uncommented)

---

## SUBMIT HANDLERS & API PAYLOADS

### BookingDialog - Create Rental (Lines 696-783)

**Validation Flow**:
1. Call `formRef.value?.validate()` - Validates required fields
2. Check duplicate rentals via `conflictDetection.checkDuplicateRental()`
3. If duplicates found, show warning dialog before proceed

**Form → API Transformation** (Lines 750-772):
```typescript
const accessoryIds = [form.value.phoneHolderId, form.value.tripodId]
  .filter((id): id is number => id !== null)

const rentalData = {
  device_id: deviceId,
  start_date: dayjs(form.value.startDate).format('YYYY-MM-DD'),
  end_date: dayjs(form.value.endDate).format('YYYY-MM-DD'),
  customer_name: form.value.customerName,
  customer_phone: form.value.customerPhone,
  destination: form.value.destination,
  ship_out_time: dayjs(shipOutTime).format('YYYY-MM-DD HH:mm:ss'),
  ship_in_time: dayjs(shipInTime).format('YYYY-MM-DD HH:mm:ss'),
  // 新：配套附件使用布尔值
  includes_handle: form.value.bundledAccessories.includes('handle'),
  includes_lens_mount: form.value.bundledAccessories.includes('lens_mount'),
  // 新：库存附件使用ID数组
  accessories: accessoryIds,
  xianyu_order_no: form.value.xianyuOrderNo,
  order_amount: form.value.orderAmount ? parseFloat(form.value.orderAmount) : undefined,
  buyer_id: form.value.buyerId,
  photo_transfer: form.value.photoTransfer  // 代传照片标记
}

await ganttStore.createRental(rentalData)
```

**API Endpoint**: `ganttStore.createRental()` (Pinia store)

### EditRentalDialogNew - Update Rental (Lines 214-257)

**Validation Flow**:
1. Call `formRef.value?.validate()` - Validates required fields
2. On validation error, return early

**Form → API Transformation** (Lines 223-246):
```typescript
const accessoryIds = [form.value.phoneHolderId, form.value.tripodId]
  .filter((id): id is number => id !== null)

const updateData = {
  device_id: form.value.deviceId,
  end_date: dayjs(form.value.endDate).format('YYYY-MM-DD'),
  customer_phone: form.value.customerPhone,
  destination: form.value.destination,
  ship_out_tracking_no: form.value.shipOutTrackingNo,
  ship_in_tracking_no: form.value.shipInTrackingNo,
  ship_out_time: form.value.shipOutTime
    ? dayjs(form.value.shipOutTime).format('YYYY-MM-DD HH:mm:ss')
    : null,
  ship_in_time: form.value.shipInTime
    ? dayjs(form.value.shipInTime).format('YYYY-MM-DD HH:mm:ss')
    : null,
  status: form.value.status,
  // 新：配套附件使用布尔值
  includes_handle: form.value.bundledAccessories.includes('handle'),
  includes_lens_mount: form.value.bundledAccessories.includes('lens_mount'),
  // 新：库存附件使用ID数组
  accessories: accessoryIds,
  xianyu_order_no: form.value.xianyuOrderNo,
  order_amount: form.value.orderAmount ? parseFloat(form.value.orderAmount) : undefined,
  buyer_id: form.value.buyerId,
  photo_transfer: form.value.photoTransfer  // 代传照片标记
}

await ganttStore.updateRental(props.rental!.id, updateData)
```

**API Endpoint**: `ganttStore.updateRental(rentalId, updateData)` (Pinia store)

---

## STATUS ENUM

**Location**: RentalShippingForm.vue (Lines 100-114)

```html
<el-select
  v-model="form.status"
  placeholder="选择租赁状态"
  style="width: 100%"
>
  <el-option label="未发货" value="not_shipped" />
  <el-option label="已发货" value="shipped" />
  <el-option label="已收回" value="returned" />
  <el-option label="已完成" value="completed" />
  <el-option label="已取消" value="cancelled" />
</el-select>
```

**Valid Values**:
- `not_shipped` - 未发货
- `shipped` - 已发货
- `returned` - 已收回
- `completed` - 已完成
- `cancelled` - 已取消

---

## DEVICE CONFLICT & AVAILABILITY CHECKING

### Device Focus Handler (BookingDialog, Lines 464-473)
```typescript
const handleDeviceFocus = async () => {
  if (!form.value.startDate || !form.value.endDate) {
    ElMessage.warning('请先选择日期后查看设备可用性')
    return
  }

  if (!availability.deviceAvailability.value.checked) {
    await checkAvailabilities()
  }
}
```

### Accessory Focus Handler (BookingDialog, Lines 476-485)
```typescript
const handleAccessoryFocus = async () => {
  if (!form.value.startDate || !form.value.endDate) {
    ElMessage.warning('请先选择日期后查看附件可用性')
    return
  }

  if (!availability.accessoryAvailability.value.checked) {
    await checkAvailabilities()
  }
}
```

### Check Availabilities (BookingDialog, Lines 448-461)
```typescript
const checkAvailabilities = async () => {
  if (!form.value.startDate || !form.value.endDate) return

  const params = {
    startDate: dayjs(form.value.startDate).format('YYYY-MM-DD'),
    endDate: dayjs(form.value.endDate).format('YYYY-MM-DD'),
    logisticsDays: form.value.logisticsDays
  }

  await Promise.all([
    availability.checkDevicesAvailability(deviceManagement.devices.value, params),
    availability.checkAccessoriesAvailability(deviceManagement.accessories.value, params)
  ])
}
```

### Device Change Conflict Warning (EditRentalDialogNew, Lines 270-305)
```typescript
const handleDeviceChange = async (deviceId: number) => {
  if (!props.rental) return

  const selectedDevice = deviceManagement.devices.value.find(d => d.id === deviceId)
  if (!selectedDevice) return

  try {
    const shipOutTime = props.rental.ship_out_time || props.rental.start_date
    const shipInTime = props.rental.ship_in_time || props.rental.end_date

    const hasConflict = await conflictDetection.checkDeviceConflict({
      deviceId,
      startDate: shipOutTime,
      endDate: shipInTime,
      excludeRentalId: props.rental.id
    })

    if (hasConflict) {
      ElMessageBox.confirm(
        `设备 "${selectedDevice.name}" 在该时间段有冲突，确定要选择吗？`,
        '设备冲突警告',
        {
          confirmButtonText: '确定选择',
          cancelButtonText: '取消',
          type: 'warning'
        }
      ).catch(() => {
        if (props.rental) {
          form.value.deviceId = props.rental.device_id  // Reset to original
        }
      })
    }
  } catch (error) {
    console.error('检查设备冲突失败:', error)
  }
}
```

### Accessory Change Conflict Warning (EditRentalDialogNew, Lines 377-396)
```typescript
const handleAccessoryChange = async (accessoryIds: number[]) => {
  const newAccessoryIds = accessoryIds.filter(id => !form.value.accessories.includes(id))

  for (const accessoryId of newAccessoryIds) {
    const accessory = deviceManagement.accessories.value.find(a => a.id === accessoryId)
    if (accessory && accessory.isAvailable === false) {
      ElMessageBox.confirm(
        `附件 "${accessory.name}" 在该时间段有冲突，确定要选择吗？`,
        '附件冲突警告',
        {
          confirmButtonText: '确定选择',
          cancelButtonText: '取消',
          type: 'warning'
        }
      ).catch(() => {
        form.value.accessories = form.value.accessories.filter(id => id !== accessoryId)
      })
    }
  }
}
```

---

## ASYNC API CALLS IN FORMS

### Find Available Slot (BookingDialog, Lines 488-534)
```typescript
const findAvailableSlot = async () => {
  if (!canSearchSlot.value) {
    ElMessage.warning('请先完善日期和物流信息')
    return
  }

  // 获取当前选择的设备型号的 model_id
  let modelId = ''
  if (props.selectedDeviceModel) {
    const selectedModel = deviceManagement.deviceModels.value.find(
      (m: any) => m.display_name === props.selectedDeviceModel
    )
    if (selectedModel) {
      modelId = selectedModel.id.toString()
    }
  }

  if (!modelId) {
    ElMessage.warning('请先在甘特图中选择设备型号筛选')
    return
  }

  searching.value = true
  try {
    const result = await ganttStore.findAvailableSlot(
      dayjs(form.value.startDate).format('YYYY-MM-DD'),
      dayjs(form.value.endDate).format('YYYY-MM-DD'),
      form.value.logisticsDays,
      modelId,
      false  // is_accessory
    )

    if (result.device) {
      availableSlot.value = result
      form.value.selectedDeviceId = result.device.id
      ElMessage.success(`找到可用设备: ${result.device.name}`)
    } else {
      throw new Error('在指定时间段内没有可用设备')
    }
  } catch (error) {
    ElMessage.error((error as Error).message)
    availableSlot.value = null
  } finally {
    searching.value = false
  }
}
```

### Check Duplicate Rental (BookingDialog, Lines 704-733)
```typescript
const duplicateCheck = await conflictDetection.checkDuplicateRental({
  customerName: form.value.customerName,
  destination: form.value.destination
})

if (duplicateCheck.hasDuplicate) {
  try {
    let duplicateInfo = '检测到可能重复的租赁记录：\n\n'
    duplicateCheck.duplicates.forEach((duplicate: any, index: number) => {
      duplicateInfo += `${index + 1}. 设备：${duplicate.device_name}\n`
      duplicateInfo += `   客户：${duplicate.customer_name}\n`
      duplicateInfo += `   地址：${duplicate.destination}\n`
      duplicateInfo += `   时间：${duplicate.start_date} 至 ${duplicate.end_date}\n`
      duplicateInfo += `   状态：${duplicate.status}\n\n`
    })
    duplicateInfo += '是否仍要继续创建新的租赁记录？'

    await ElMessageBox.confirm(
      duplicateInfo,
      '重复租赁提醒',
      {
        type: 'warning',
        confirmButtonText: '继续创建',
        cancelButtonText: '取消'
      }
    )
  } catch {
    return
  }
}
```

---

## COMPLEXITY SUMMARY FOR MOBILE VERSION

### High Complexity Areas:
1. **Dynamic device/accessory filtering** - Filtered based on name/model field patterns
2. **Date interdependencies** - startDate → endDate validation, date changes trigger availability checks
3. **Multiple async operations** - Xianyu order fetching, availability checking, conflict detection
4. **Form data transformation** - UI format → API format (especially accessories & bundled items)
5. **Conditional field display** - Accessories summary shown only if any selected
6. **Auto-extraction** - Phone number extraction from destination field
7. **Dual form modes** - Create vs Edit with different validation rules and fields
8. **Conflict warning dialogs** - Interactive confirmation on device/accessory conflicts

### Accessibility/Visibility Rules:
- Phone holders & tripods filtered from all accessories by name/model matching
- Serial number display conditional on presence
- Conflict tags shown based on device.conflicted flag
- Accessory summary section shown only if hasSelectedAccessories computed value is true
- Options disabled based on availability.accessoryAvailability.value.checked && !availability.isAccessoryAvailable()

### Data Flow:
```
Form → Validation → Duplicate Check → Transform → API Call → Success/Error
        ↓
    Availability Check (on date change or focus)
        ↓
    Watch destination → Extract Phone
```

