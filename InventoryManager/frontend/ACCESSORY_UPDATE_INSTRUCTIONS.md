# Frontend Accessory Simplification Updates

## Overview
This document contains instructions for manually updating the frontend components to support the new bundled accessory model.

## Changes Required

### 1. BookingDialog.vue

Replace the current single multi-select dropdown for accessories with:

#### Template Changes (around line 175):
```vue
<!-- 配套附件 - 复选框 -->
<el-form-item label="配套附件">
  <el-checkbox-group v-model="form.bundledAccessories">
    <el-checkbox label="handle">手柄</el-checkbox>
    <el-checkbox label="lens_mount">镜头支架</el-checkbox>
  </el-checkbox-group>
  <div class="form-tip">手柄和镜头支架已与设备配齐，无需选择具体编号</div>
</el-form-item>

<!-- 库存附件 - 下拉选择 -->
<el-form-item label="手机支架">
  <el-select 
    v-model="form.phoneHolderId" 
    placeholder="选择手机支架(可选)" 
    clearable
    @focus="handleAccessoryFocus"
  >
    <el-option
      v-for="holder in phoneHolders"
      :key="holder.id"
      :label="`${holder.name} ${holder.is_available ? '(可用)' : '(冲突)'}`"
      :value="holder.id"
      :disabled="!holder.is_available"
    />
  </el-select>
</el-form-item>

<el-form-item label="三脚架">
  <el-select 
    v-model="form.tripodId" 
    placeholder="选择三脚架(可选)" 
    clearable
    @focus="handleAccessoryFocus"
  >
    <el-option
      v-for="tripod in tripods"
      :key="tripod.id"
      :label="`${tripod.name} ${tripod.is_available ? '(可用)' : '(冲突)'}`"
      :value="tripod.id"
      :disabled="!tripod.is_available"
    />
  </el-select>
</el-form-item>
```

#### Script Changes (around line 323):
```typescript
// Update form state
const form = ref({
  startDate: null as Date | null,
  endDate: null as Date | null,
  logisticsDays: 1,
  selectedDeviceId: null as number | null,
  customerName: '',
  customerPhone: '',
  destination: '',
  // NEW: Split accessories into bundled and inventory
  bundledAccessories: [] as ('handle' | 'lens_mount')[],
  phoneHolderId: null as number | null,
  tripodId: null as number | null,
  xianyuOrderNo: '',
  orderAmount: '',
  buyerId: ''
})

// Add computed properties for filtered accessories
const phoneHolders = computed(() => {
  return deviceManagement.accessories.value.filter(a => 
    a.name.includes('手机支架') || a.name.toLowerCase().includes('phone')
  )
})

const tripods = computed(() => {
  return deviceManagement.accessories.value.filter(a => 
    a.name.includes('三脚架') || a.name.toLowerCase().includes('tripod')
  )
})
```

#### Submit Method Update:
```typescript
const handleSubmit = async () => {
  // ... existing validation code ...
  
  const payload = {
    device_id: form.value.selectedDeviceId,
    start_date: dayjs(form.value.startDate).format('YYYY-MM-DD'),
    end_date: dayjs(form.value.endDate).format('YYYY-MM-DD'),
    customer_name: form.value.customerName,
    customer_phone: form.value.customerPhone || '',
    destination: form.value.destination,
    xianyu_order_no: form.value.xianyuOrderNo || '',
    order_amount: form.value.orderAmount ? parseFloat(form.value.orderAmount) : null,
    buyer_id: form.value.buyerId || '',
    ship_out_time: formatShipTime(shipOutTime),
    ship_in_time: formatShipTime(shipInTime),
    
    // NEW: Convert UI format to API format
    includes_handle: form.value.bundledAccessories.includes('handle'),
    includes_lens_mount: form.value.bundledAccessories.includes('lens_mount'),
    accessories: [form.value.phoneHolderId, form.value.tripodId]
      .filter((id): id is number => id !== null)
  }
  
  // ... rest of submit code ...
}
```

### 2. EditRentalDialogNew.vue

Similar changes as BookingDialog.vue, plus add data loading:

```typescript
const loadRentalData = (rental: any) => {
  // ... existing field loading ...
  
  // NEW: Load bundled accessories
  form.value.bundledAccessories = []
  if (rental.includes_handle) {
    form.value.bundledAccessories.push('handle')
  }
  if (rental.includes_lens_mount) {
    form.value.bundledAccessories.push('lens_mount')
  }
  
  // Load inventory accessories
  const phoneHolder = rental.accessories?.find((a: any) => a.type === 'phone_holder')
  form.value.phoneHolderId = phoneHolder?.id || null
  
  const tripod = rental.accessories?.find((a: any) => a.type === 'tripod')
  form.value.tripodId = tripod?.id || null
}
```

### 3. RentalAccessorySelector.vue (if exists)

If this component exists as a separate component, apply similar split logic:
- Checkboxes for handle and lens mount
- Dropdowns for phone holder and tripod

### 4. GanttRow.vue

Update tooltip to show bundled accessories:

```vue
<template #content>
  <div class="rental-tooltip">
    <p><strong>订单 #{{ rental.id }}</strong></p>
    <p>客户: {{ rental.customer_name }}</p>
    <div v-if="rental.accessories && rental.accessories.length > 0">
      <p class="accessories-title">附件:</p>
      <ul class="accessories-list">
        <li v-for="(acc, index) in rental.accessories" :key="index">
          {{ acc.name }}
          <el-tag v-if="acc.is_bundled" size="small" type="info">配套</el-tag>
          <span v-else-if="acc.serial_number" class="serial">({{ acc.serial_number }})</span>
        </li>
      </ul>
    </div>
  </div>
</template>
```

## Testing Checklist

After making these changes:

1. ✅ Create new rental with bundled accessories selected
2. ✅ Create new rental with inventory accessories selected
3. ✅ Create new rental with both types
4. ✅ Edit existing rental and verify data loads correctly
5. ✅ Check Gantt chart displays accessories correctly
6. ✅ Verify printing shows all accessories
7. ✅ Test historical data displays properly

## Notes

- The type definitions in `frontend/src/types/rental.ts` are already created and should be imported
- Use `convertFormDataToCreatePayload()` helper function for API calls
- Use `convertRentalToFormData()` helper function when loading existing rentals
