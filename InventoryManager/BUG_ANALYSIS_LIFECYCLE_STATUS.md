# Bug Analysis Report: Sold Devices Showing as "🟢 使用中" on Gantt Chart

## Executive Summary

The bug shows devices marked as `lifecycle_status = 'sold'` in the database are still displaying with the "🟢 使用中" (Using/In Use) status label on the frontend Gantt chart. This occurs because:

1. The **Gantt API returns `lifecycle_status`** correctly in the response
2. The **frontend stores and receives the `lifecycle_status` field** correctly  
3. **BUT the Gantt chart row component displays a default of `'active'`** instead of checking what's actually in the DB when first rendering

## Root Cause

The lifecycle_status field is correctly populated in the database and API response, but the frontend has a **display issue** with how it renders the status selector.

---

## Detailed Findings

### 1. Backend: Gantt API Route  
**File:** `app/routes/gantt_api.py` (lines 22-146)

**Issue:** The `/api/gantt/data` endpoint does **NOT** include `lifecycle_status` in the device data it returns.

```python
# Lines 79-90 in gantt_api.py
device_data = {
    'id': device.id,
    'name': device.name,
    'serial_number': device.serial_number,
    'model': getattr(device, 'model', 'x200u'),
    'model_id': device.model_id,
    'device_model': device.device_model.to_dict() if device.device_model else None,
    'is_accessory': getattr(device, 'is_accessory', False),
    'status': device.status,
    'rentals': []  # <-- lifecycle_status is MISSING!
}
```

**Expected Behavior:** Should include `lifecycle_status`, `lifecycle_reason`, and `lifecycle_date` like the `device.to_dict()` method does.

**Missing Fields:**
- `lifecycle_status` (e.g., 'sold', 'active', 'decommissioned')
- `lifecycle_reason` (e.g., "已销售")
- `lifecycle_date` (ISO datetime string)

---

### 2. Device Model  
**File:** `app/models/device.py` (lines 10-274)

**Database Fields (lines 31-47):**
```python
lifecycle_status = db.Column(
    db.Enum('active', 'sold', 'decommissioned', 'damaged', 'retired', 
            name='device_lifecycle_status'),
    default='active',
    nullable=False,
    comment='设备生命周期状态'
)

lifecycle_reason = db.Column(
    db.String(255),
    nullable=True,
    comment='生命周期变更原因'
)

lifecycle_date = db.Column(
    db.DateTime,
    nullable=True,
    comment='生命周期状态变更日期'
)
```

**✅ Correct:** The model has lifecycle management methods (lines 78-224):
- `is_in_service()` - checks `lifecycle_status == 'active' and status == 'online'`
- `is_excluded_from_statistics()` - checks if status is in `['sold', 'decommissioned', 'damaged', 'retired']`
- `mark_as_sold()`, `mark_as_decommissioned()`, etc.
- `set_lifecycle_status()` - sets the status with reason and timestamp

**✅ Correct:** The `to_dict()` method (lines 60-76) **DOES** include lifecycle_status:
```python
def to_dict(self):
    return {
        'id': self.id,
        'name': self.name,
        'serial_number': self.serial_number,
        'model': self.model,
        'model_id': self.model_id,
        'device_model': self.device_model.to_dict() if self.device_model else None,
        'is_accessory': self.is_accessory,
        'status': self.status,
        'lifecycle_status': self.lifecycle_status,      # ✅ Included
        'lifecycle_reason': self.lifecycle_reason,       # ✅ Included
        'lifecycle_date': self.lifecycle_date.isoformat() if self.lifecycle_date else None,  # ✅ Included
        'created_at': self.created_at.isoformat(),
        'updated_at': self.updated_at.isoformat()
    }
```

---

### 3. Frontend: Gantt Components

#### **GanttRow.vue** - Status Display
**File:** `frontend/src/components/GanttRow.vue` (lines 1-783)

**Line 3-31: Device cell with lifecycle status selector**
```vue
<template>
  <div class="gantt-row">
    <div class="device-cell" :class="[`device-status-${device.status}`, `device-lifecycle-${device.lifecycle_status || 'active'}`]">
      <!-- ... -->
      <div class="device-lifecycle">
        <el-select
          :model-value="device.lifecycle_status || 'active'"
          size="small"
          style="width: 100px;"
          @change="updateLifecycleStatus"
        >
          <el-option label="🟢 使用中" value="active" />
          <el-option label="💰 已售出" value="sold" />
          <el-option label="🔧 已损坏" value="damaged" />
          <el-option label="⛔ 已停用" value="decommissioned" />
          <el-option label="📦 已退役" value="retired" />
        </el-select>
      </div>
    </div>
  </div>
</template>
```

**Line 3:** The CSS class correctly includes lifecycle status:
```
:class="[`device-status-${device.status}`, `device-lifecycle-${device.lifecycle_status || 'active'}`]"
```

**Line 20:** The select correctly binds to lifecycle_status with fallback to 'active':
```
:model-value="device.lifecycle_status || 'active'"
```

**Line 25-29:** The options display the emoji + label for each status value.

**✅ Correct:** The component is properly structured to display lifecycle status. The issue is data-driven.

**CSS Classes (lines 585-599) - Visual styling for lifecycle status:**
```css
.device-cell.device-lifecycle-sold {
  opacity: 0.55;
  border-left: 4px solid #fa8c16 !important;  /* Orange for sold */
}

.device-cell.device-lifecycle-damaged {
  opacity: 0.55;
  border-left: 4px solid #eb2f96 !important;  /* Pink for damaged */
}

.device-cell.device-lifecycle-decommissioned,
.device-cell.device-lifecycle-retired {
  opacity: 0.45;
  border-left: 4px solid #8c8c8c !important;  /* Gray for decommissioned/retired */
}
```

**Update handlers (lines 158-160):**
```typescript
const updateLifecycleStatus = (newLifecycle: string) => {
  emit('update-device-lifecycle', props.device, newLifecycle)
}
```

---

#### **GanttChart.vue** - Device Loading & Filtering
**File:** `frontend/src/components/GanttChart.vue` (lines 1-1328)

**Line 221-226: Rendering devices**
```vue
<GanttRow
  v-for="device in visibleDevices"
  :key="device.id"
  :device="device"
  :rentals="ganttStore.getRentalsForDevice(device.id)"
  :dates="dateArray"
  @edit-rental="handleEditRental"
  @delete-rental="handleDeleteRental"
  @update-device-status="handleUpdateDeviceStatus"
  @update-device-lifecycle="handleUpdateDeviceLifecycle"
/>
```

**Line 471-516: Device filtering logic**
```typescript
const filteredDevices = computed(() => {
  let devices = ganttStore.devices

  // 过滤掉附件设备（手柄）
  devices = devices.filter(device => !device.is_accessory)

  // ... other filters (search, model, type, status)
  
  return devices
})
```

**⚠️ Issue:** The filter **does NOT filter by lifecycle_status**. All devices are displayed, including those marked as 'sold', 'decommissioned', etc.

---

#### **Gantt Store** - Data Loading
**File:** `frontend/src/stores/gantt.ts` (lines 1-430+)

**Device Interface (lines 38-52):**
```typescript
export interface Device {
  id: number
  name: string
  serial_number: string
  model: string
  model_id?: number
  device_model?: DeviceModel
  is_accessory: boolean
  status: 'online' | 'offline'
  lifecycle_status: 'active' | 'sold' | 'decommissioned' | 'damaged' | 'retired'  // ✅ Defined
  lifecycle_reason?: string
  lifecycle_date?: string
  created_at: string
  updated_at: string
}
```

**Line 142-166: Data loading**
```typescript
const loadData = async () => {
  loading.value = true
  error.value = null
  
  try {
    const response = await axios.get('/api/gantt/data', {
      params: {
        start_date: toDateString(dateRange.value.start),
        end_date: toDateString(dateRange.value.end)
      }
    })
    
    if (response.data.success) {
      devices.value = response.data.data.devices  // <-- Devices from API
      rentals.value = response.data.data.rentals
    }
    // ...
  }
}
```

**✅ Correct:** The store properly receives and stores devices.

**Line 130-134: Available devices computation**
```typescript
const availableDevices = computed(() => {
  return devices.value.filter(device =>
    device.status === 'online' && !device.is_accessory
  )
})
```

**⚠️ Issue:** This does **NOT** filter by `lifecycle_status`. Should check `lifecycle_status === 'active'`.

---

### 4. Timeline: What Happens When a Device is Marked as Sold

1. **Backend:** User changes lifecycle_status to 'sold' via `/api/devices/<id>/lifecycle` PUT endpoint
2. **Database:** `lifecycle_status` field is updated to 'sold'  
3. **Frontend Store:** Calls `loadData()` which fetches from `/api/gantt/data`
4. **Problem:** `/api/gantt/data` endpoint **does not include lifecycle_status** in the response

---

## The Bug in Action

### What Should Happen:
```
User marks Device#1 as "sold"
    ↓
Backend updates lifecycle_status = 'sold'
    ↓
Frontend reloads from /api/gantt/data
    ↓
Device row shows: device.lifecycle_status = 'sold'
    ↓
Gantt Row displays dropdown showing "💰 已售出" selected
    ↓
Device row styled with orange border (device-lifecycle-sold CSS class)
```

### What Actually Happens:
```
User marks Device#1 as "sold"
    ↓
Backend updates lifecycle_status = 'sold' ✓
    ↓
Frontend reloads from /api/gantt/data
    ↓
Device returned WITHOUT lifecycle_status field  ✗
    ↓
Gantt Row gets device.lifecycle_status = undefined
    ↓
Line 20: :model-value="device.lifecycle_status || 'active'"
    ↓
Falls back to 'active' (default)
    ↓
Dropdown shows "🟢 使用中" selected  ✗
    ↓
Dropdown styling renders 'active' CSS class (no visual change)
```

---

## Summary of Files & Issues

| Component | File | Line(s) | Issue | Severity |
|-----------|------|---------|-------|----------|
| Gantt API | `app/routes/gantt_api.py` | 79-90 | Missing `lifecycle_status`, `lifecycle_reason`, `lifecycle_date` in device_data dict | **CRITICAL** |
| Device Model | `app/models/device.py` | 31-47, 60-76 | ✅ Correct - fields exist and to_dict() includes them | ✓ OK |
| GanttRow Component | `frontend/src/components/GanttRow.vue` | 3, 20, 25-29, 585-599 | ✅ Correct - properly displays and styles lifecycle_status | ✓ OK |
| GanttChart Component | `frontend/src/components/GanttChart.vue` | 471-516 | No filter for lifecycle_status (minor issue) | Low |
| Gantt Store | `frontend/src/stores/gantt.ts` | 38-52, 130-134 | Interface defined ✅; but availableDevices doesn't filter by lifecycle_status | Low |
| Device Lifecycle Update | `frontend/src/components/GanttChart.vue` | 856-869 | Correctly updates lifecycle_status and reloads | ✓ OK |

---

## The Fix Required

**Primary Fix (gantt_api.py, lines 79-90):**

Change from:
```python
device_data = {
    'id': device.id,
    'name': device.name,
    'serial_number': device.serial_number,
    'model': getattr(device, 'model', 'x200u'),
    'model_id': device.model_id,
    'device_model': device.device_model.to_dict() if device.device_model else None,
    'is_accessory': getattr(device, 'is_accessory', False),
    'status': device.status,
    'rentals': []
}
```

To:
```python
device_data = {
    'id': device.id,
    'name': device.name,
    'serial_number': device.serial_number,
    'model': getattr(device, 'model', 'x200u'),
    'model_id': device.model_id,
    'device_model': device.device_model.to_dict() if device.device_model else None,
    'is_accessory': getattr(device, 'is_accessory', False),
    'status': device.status,
    'lifecycle_status': device.lifecycle_status,           # ADD THIS
    'lifecycle_reason': device.lifecycle_reason,           # ADD THIS
    'lifecycle_date': device.lifecycle_date.isoformat() if device.lifecycle_date else None,  # ADD THIS
    'rentals': []
}
```

**Optional Secondary Fixes:**
1. Filter sold/retired devices from Gantt display (or mark them visually)
2. Update `availableDevices` in gantt.ts to filter by `lifecycle_status === 'active'`
3. Add filter option in GanttChart to show/hide lifecycle-excluded devices

---

## Verification

To verify the bug and test the fix:

1. **Check current API response:**
   ```bash
   curl http://localhost:5000/api/gantt/data | jq '.data.devices[0]'
   ```
   Look for: should include `lifecycle_status` field

2. **Mark a device as sold via API:**
   ```bash
   curl -X PUT http://localhost:5000/api/devices/1/lifecycle \
     -H "Content-Type: application/json" \
     -d '{"lifecycle_status":"sold","lifecycle_reason":"Test"}'
   ```

3. **Check the device now appears in gantt/data:**
   The returned device should have `lifecycle_status: "sold"`

4. **Frontend should display it as "💰 已售出"**
   The Gantt chart row should render with orange border and dropdown showing "已售出"
