# Quick Reference: Lifecycle Status Bug

## One-Line Summary
**Gantt API endpoint `/api/gantt/data` returns device data WITHOUT the `lifecycle_status` field, causing the frontend to show "🟢 使用中" for all devices instead of the correct status.**

---

## Files & Line Numbers

### Critical Issue
| File | Lines | Problem |
|------|-------|---------|
| `app/routes/gantt_api.py` | **79-90** | Missing `lifecycle_status`, `lifecycle_reason`, `lifecycle_date` in device dict |

### Components (Status: ✅ OK)
| File | Lines | Status |
|------|-------|--------|
| `app/models/device.py` | 31-47, 60-76 | ✅ Model defines fields and includes in `to_dict()` |
| `frontend/src/components/GanttRow.vue` | 3, 20, 25-29, 585-599 | ✅ Component correctly displays lifecycle_status |
| `frontend/src/stores/gantt.ts` | 38-52 | ✅ Interface defined correctly |
| `frontend/src/components/GanttChart.vue` | 856-869 | ✅ Update handler works correctly |

---

## The Missing 3 Lines

In `app/routes/gantt_api.py` at **line 88** (before `'rentals': []`), add:

```python
'lifecycle_status': device.lifecycle_status,
'lifecycle_reason': device.lifecycle_reason,
'lifecycle_date': device.lifecycle_date.isoformat() if device.lifecycle_date else None,
```

### Before (lines 79-90):
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

### After:
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
    'lifecycle_status': device.lifecycle_status,           # ← ADD
    'lifecycle_reason': device.lifecycle_reason,           # ← ADD
    'lifecycle_date': device.lifecycle_date.isoformat() if device.lifecycle_status else None,  # ← ADD
    'rentals': []
}
```

---

## Why This Bug Happens

```
DB: Device(id=1, lifecycle_status='sold') ✅
  ↓
Device.to_dict() includes lifecycle_status ✅
  ↓
BUT gantt_api.py manually builds dict ❌
  ↓
Manually built dict missing lifecycle fields ❌
  ↓
Frontend receives undefined ❌
  ↓
Frontend fallback: device.lifecycle_status || 'active' ❌
  ↓
Shows "🟢 使用中" instead of "💰 已售出" ❌
```

---

## Testing the Fix

1. Mark a device as sold:
   ```bash
   curl -X PUT http://localhost:5000/api/devices/1/lifecycle \
     -H "Content-Type: application/json" \
     -d '{"lifecycle_status":"sold"}'
   ```

2. Check API response includes lifecycle_status:
   ```bash
   curl http://localhost:5000/api/gantt/data | jq '.data.devices[0]'
   # Should see: "lifecycle_status": "sold"
   ```

3. Refresh Gantt chart in browser - should now show:
   - Dropdown: "💰 已售出" ✅
   - Border: Orange ✅
   - Opacity: 0.55 ✅

---

## Impact Summary

| Aspect | Before Fix | After Fix |
|--------|-----------|-----------|
| API Response | Missing lifecycle_status | Includes lifecycle_status |
| UI Display | "🟢 使用中" for all devices | Correct status shown |
| Visual Styling | Default styling | Orange/gray/pink as appropriate |
| User Confusion | High - can't tell sold devices | None - clear indication |

---

## Related Code Paths

### When User Clicks Dropdown to Mark Device as Sold:
1. `GanttRow.vue` line 159 → emits `update-device-lifecycle`
2. `GanttChart.vue` line 856-869 → calls `ganttStore.updateDeviceLifecycle()`
3. `gantt.ts` line 336-354 → PUT to `/api/devices/<id>/lifecycle`
4. `device_api.py` line 249-292 → Updates DB + returns updated device
5. `ganttStore.loadData()` → Reloads from `/api/gantt/data`
6. ⚠️ **At step 5, lifecycle_status should now be included** (after fix)

---

## Alternative Fix (More Comprehensive)

Instead of adding 3 lines, refactor to use `device.to_dict()`:

```python
# Current approach (manual dict construction)
device_data = {
    'id': device.id,
    'name': device.name,
    # ... 10+ manual fields
}

# Better approach (use to_dict())
device_data = device.to_dict()
# This automatically includes ALL fields including lifecycle_status
```

But be careful: `to_dict()` includes `created_at`, `updated_at` which frontend may not need. Keep the 3-line fix if you want to be minimal and explicit.

---

## Severity: **CRITICAL** 🔴

- **Users can't see which devices are sold/decommissioned**
- **Visual indicators (color, opacity) don't appear**
- **Can mislead operations staff about device availability**
- **Fix is trivial: add 3 lines of code**

---

For full analysis, see: `BUG_ANALYSIS_LIFECYCLE_STATUS.md`
For data flow diagram, see: `BUG_FLOW_DIAGRAM.txt`
