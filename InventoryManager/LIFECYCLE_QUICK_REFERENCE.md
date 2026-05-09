# Device Lifecycle Management - Quick Reference

**Version:** 1.0  
**Last Updated:** May 9, 2026  

---

## Quick Start

### Mark a Device as Sold (API)

```bash
curl -X PUT http://localhost:5000/api/devices/1/lifecycle \
  -H "Content-Type: application/json" \
  -d '{
    "lifecycle_status": "sold",
    "lifecycle_reason": "Sold to Customer XYZ"
  }'
```

### Mark a Device as Sold (Quick Endpoint)

```bash
curl -X PUT http://localhost:5000/api/devices/1/mark-sold \
  -H "Content-Type: application/json" \
  -d '{"reason": "No longer needed"}'
```

### Get Device Lifecycle Summary

```bash
curl -X GET http://localhost:5000/api/devices/lifecycle/summary
```

### Get All Sold Devices

```bash
curl -X GET "http://localhost:5000/api/devices/lifecycle/list?status=sold"
```

---

## Lifecycle Statuses

| Status | Meaning | Excluded from Stats | Can Rent |
|--------|---------|-------------------|----------|
| **active** | Device in service | ❌ No | ✅ Yes |
| **sold** | Permanently sold | ✅ Yes | ❌ No |
| **decommissioned** | End-of-life | ✅ Yes | ❌ No |
| **damaged** | Broken/repair needed | ✅ Yes | ❌ No |
| **retired** | Voluntarily removed | ✅ Yes | ❌ No |

---

## Model Methods

### Check Device Status

```python
device = Device.query.get(1)

# Is device available for rental?
if device.is_in_service():
    print("Device can be rented")

# Is device excluded from statistics?
if device.is_excluded_from_statistics():
    print("Device won't count in statistics")

# Can create new rental?
if device.can_create_new_rental():
    print("Safe to create rental")
```

### Mark Device Status

```python
device = Device.query.get(1)

# Mark as sold
device.mark_as_sold("Sold to XYZ Company")
db.session.commit()

# Mark as decommissioned
device.mark_as_decommissioned("End of life")
db.session.commit()

# Mark as damaged
device.mark_as_damaged("Screen cracked")
db.session.commit()

# Mark as retired
device.mark_as_retired("Voluntarily retired")
db.session.commit()

# Restore to active
device.restore_to_active("Repair completed")
db.session.commit()

# Generic method with validation
success, message = device.set_lifecycle_status('sold', 'Test reason')
if success:
    db.session.commit()
```

### Get Statistics

```python
# Count devices by lifecycle status
stats = Device.get_device_count_by_lifecycle_status()
# Returns: [('active', 7), ('sold', 1), ...]

# Get all active devices
active_devices = Device.get_active_devices()

# Get all excluded devices
excluded_devices = Device.get_excluded_devices()
```

---

## API Endpoints

### PUT `/api/devices/<device_id>/lifecycle`
Update device lifecycle status.

**Parameters:**
- `lifecycle_status` (required): active | sold | decommissioned | damaged | retired
- `lifecycle_reason` (optional): Text explanation

**Example:**
```json
{
  "lifecycle_status": "sold",
  "lifecycle_reason": "Sold to XYZ Company on 2026-05-09"
}
```

---

### PUT `/api/devices/<device_id>/mark-sold`
Quick endpoint to mark as sold.

**Parameters:**
- `reason` (optional): Why device was sold

---

### GET `/api/devices/lifecycle/summary`
Get summary counts by lifecycle status.

**Returns:**
```json
{
  "lifecycle_status_summary": {
    "active": 7,
    "sold": 1,
    "decommissioned": 0,
    "damaged": 0,
    "retired": 0,
    "total": 8
  },
  "active_and_online": 7,
  "excluded_from_statistics": 1,
  "available_for_rental": 7
}
```

---

### GET `/api/devices/lifecycle/list?status=<status>`
Get devices filtered by lifecycle status.

**Query Parameters:**
- `status`: all | active | sold | decommissioned | damaged | retired

**Example Responses:**

```json
// GET /api/devices/lifecycle/list?status=sold
{
  "data": [
    {
      "id": 2005,
      "name": "Device 2005",
      "lifecycle_status": "sold",
      "lifecycle_reason": "Sold to XYZ",
      "lifecycle_date": "2026-05-09T10:30:00Z",
      "is_in_service": false,
      "is_excluded_from_statistics": true
    }
  ],
  "total": 1,
  "filter": "sold"
}
```

---

## Database Schema

### Devices Table Changes

```sql
-- Three new columns added
lifecycle_status ENUM('active', 'sold', 'decommissioned', 'damaged', 'retired') 
  NOT NULL DEFAULT 'active'
lifecycle_reason VARCHAR(255) NULL
lifecycle_date DATETIME NULL

-- New index for performance
CREATE INDEX idx_devices_lifecycle_status ON devices(lifecycle_status)
```

---

## Common Tasks

### Task: Mark multiple devices as sold

**Option 1: Via curl loop**
```bash
for id in 1 2 3 4 5; do
  curl -X PUT http://localhost:5000/api/devices/$id/lifecycle \
    -H "Content-Type: application/json" \
    -d "{\"lifecycle_status\": \"sold\", \"lifecycle_reason\": \"Bulk sale\"}"
done
```

**Option 2: Via Python script**
```python
from app import create_app, db
from app.models.device import Device

app = create_app()
with app.app_context():
    device_ids = [1, 2, 3, 4, 5]
    devices = Device.query.filter(Device.id.in_(device_ids)).all()
    for device in devices:
        device.mark_as_sold("Bulk sale")
    db.session.commit()
```

### Task: Get count of excluded devices

```bash
curl -s http://localhost:5000/api/devices/lifecycle/summary \
  | jq '.data.excluded_from_statistics'
```

### Task: Find all decommissioned devices

```bash
curl -s "http://localhost:5000/api/devices/lifecycle/list?status=decommissioned" \
  | jq '.data[] | {id, name, lifecycle_reason}'
```

### Task: Restore a sold device

```python
device = Device.query.get(2005)
device.restore_to_active("Device repaired and available again")
db.session.commit()
```

---

## Troubleshooting

### Issue: Device doesn't appear in excluded count

**Cause:** Device has `lifecycle_status='active'`  
**Solution:** Update device status using API or model method

```bash
curl -X PUT http://localhost:5000/api/devices/ID/lifecycle \
  -d '{"lifecycle_status": "sold"}'
```

### Issue: Statistics still include sold device

**Cause:** Rental stats were cached or migration wasn't applied  
**Solution:** 
1. Verify migration: `flask db current` should show `001_lifecycle_mgmt`
2. Clear cache if applicable
3. Restart application

### Issue: Cannot update device status

**Cause:** Device already has that status  
**Solution:** Choose different status or don't attempt no-op updates

---

## Performance Tips

1. **Filtering by Status:** Use `/api/devices/lifecycle/list?status=<status>` instead of getting all devices
2. **Summary Stats:** Use `/api/devices/lifecycle/summary` for quick overview
3. **Database Queries:** Index on `lifecycle_status` makes filtering fast
4. **Batch Operations:** Use Python loop for bulk updates (faster than API calls)

---

## Related Documentation

- **Full Implementation Guide** → `DEVICE_LIFECYCLE_IMPLEMENTATION_GUIDE.md`
- **Deployment Guide** → `LIFECYCLE_DEPLOYMENT_GUIDE.md`
- **Implementation Status** → `IMPLEMENTATION_COMPLETE.md`
- **Data Model Analysis** → `DEVICE_DATA_MODEL_ANALYSIS.md`
- **Relationship Diagrams** → `DEVICE_RELATIONSHIP_DIAGRAM.md`

---

## Common Questions

**Q: Will marking a device as sold delete its rental history?**  
A: No! All rental records are preserved. The device just won't count in new statistics.

**Q: Can I restore a sold device back to active?**  
A: Yes! Use `restore_to_active()` method or set status back to 'active'.

**Q: Does this affect existing rental records?**  
A: No! Existing rentals are unchanged. The status only affects future statistics.

**Q: Are hardcoded EXCLUDED_DEVICE_NAMES devices still excluded?**  
A: Yes! Both mechanisms work together for full backward compatibility.

**Q: What if I have a device that's both hardcoded AND has lifecycle_status=sold?**  
A: It will be excluded via both mechanisms (no double-counting).

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-05-09 | Initial implementation |

---

Generated by Implementation Automation  
For support, refer to full documentation files
