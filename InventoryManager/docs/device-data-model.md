# Device Data Model Analysis - Inventory Manager

## Summary
This document provides a comprehensive overview of the device data model in the XianyuAutoAgent InventoryManager project and recommendations for marking devices as permanently sold/decommissioned to exclude them from rental statistics.

---

## Current Device Data Model

### 1. Device Model (`app/models/device.py`)

The core device record has the following structure:

```python
class Device(db.Model):
    __tablename__ = 'devices'
    
    # Primary Key
    id = db.Column(db.Integer, primary_key=True)
    
    # Basic Information
    name = db.Column(db.String(100), nullable=False)           # Device name (e.g., "2001", "3005")
    serial_number = db.Column(db.String(100), unique=True)    # Unique serial number
    model = db.Column(db.String(50), nullable=False)           # Model code (e.g., "x200u")
    model_id = db.Column(db.Integer, db.ForeignKey('device_models.id'))  # FK to DeviceModel
    is_accessory = db.Column(db.Boolean, default=False)        # Is it an accessory?
    
    # Status Information
    status = db.Column(
        db.Enum('online', 'offline'),
        default='online'
    )
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    rentals = db.relationship('Rental', backref='device', lazy='dynamic')
    audit_logs = db.relationship('AuditLog', backref='device', lazy='dynamic')
```

**Key Fields:**
- **id**: Unique database identifier
- **name**: Device name/number (PRIMARY identifier used by users, e.g., "2001", "2005", "3005")
- **serial_number**: Hardware serial number (unique constraint)
- **status**: Currently only supports 'online' or 'offline' (limited scope)
- **is_accessory**: Boolean flag to distinguish main devices from accessories
- **model_id**: Links to DeviceModel for pricing/value information

### 2. Device Status Field

**Current Implementation:**
- Field: \`status\` (Enum: 'online', 'offline')
- Scope: Very limited, only indicates network/availability status, NOT lifecycle status

**Problem:** The current status enum doesn't support marking devices as "sold", "decommissioned", or "excluded from rental statistics".

---

## How Devices are Currently Used in Rental Statistics

### Rental Statistics API (\`app/routes/rental_stats_api.py\`)

**Critical Discovery:** There's ALREADY an exclusion mechanism in place!

```python
# Lines 19-31: Hardcoded Exclusion
EXCLUDED_DEVICE_NAMES = {'2005', '3005', '3006', '代发01', '代发02', '代发03', '代发 04 深圳'}

def _get_excluded_device_ids_from_db():
    """Returns set of device IDs to exclude (matches by device.name)"""
    excluded = Device.query.filter(Device.name.in_(EXCLUDED_DEVICE_NAMES)).all()
    return {d.id for d in excluded}
```

**Current Approach:** Devices are excluded by adding their \`name\` to the \`EXCLUDED_DEVICE_NAMES\` set.

**Usage:** In \`/periodic\` endpoint:
```python
excluded = _get_excluded_device_ids_from_db()
device_query = Device.query.filter(
    Device.is_accessory == False,
    ~Device.id.in_(excluded)  # Explicitly exclude these device IDs
)
```

This exclusion is applied to:
- Device count calculations (how many devices are "active")
- Rental rate calculations
- Revenue calculations
- Depreciation calculations

---

## Rental Model Relationship to Devices

### Rental Model (\`app/models/rental.py\`)

A device can have MANY rentals across its lifetime. Existing rental records remain unchanged - only future statistics exclude the device.

**Key Point:** Devices marked as sold/decommissioned will:
1. Keep all historical rental records (audit trail preserved)
2. Be excluded from future statistics calculations
3. Prevent new rentals from being created with that device

---

## Recommended Solution: Add Device Lifecycle Status

### Option 1: Recommended - Add New Field (Non-Breaking)

Add a new field to the Device model to explicitly track device lifecycle status:

```python
class Device(db.Model):
    # ... existing fields ...
    
    # Device Lifecycle Status (NEW FIELD)
    lifecycle_status = db.Column(
        db.Enum('active', 'sold', 'decommissioned', 'damaged', 'retired'),
        default='active',
        comment='Device lifecycle status'
    )
    
    # Optional: Metadata for why device was removed
    lifecycle_reason = db.Column(db.String(255), nullable=True, comment='Reason for status change')
    lifecycle_date = db.Column(db.DateTime, nullable=True, comment='Date of status change')
    
    # ... rest of model ...
```

**Lifecycle Status Values:**
- **active** (default): Device is in active rental service
- **sold**: Device has been sold off (permanent removal from inventory)
- **decommissioned**: Device is obsolete/end-of-life (permanent removal)
- **damaged**: Device is damaged and not operational (temporary/permanent)
- **retired**: Device voluntarily retired from service (soft removal)

---

## Implementation Steps

### Step 1: Create Database Migration

Create a new migration file to add the new columns to the devices table.

### Step 2: Update Device Model

Add the new fields and helper methods to the Device model.

### Step 3: Update Rental Statistics API

Replace the hardcoded EXCLUDED_DEVICE_NAMES with a database query that checks lifecycle_status.

### Step 4: Add Device Lifecycle API Endpoint

Create endpoint to manage device lifecycle status via API.

### Step 5: Add Admin UI

Create a simple form in the device management interface to mark devices as sold/decommissioned.

---

## API Usage Examples

### Mark a Device as Sold

```bash
PUT /api/devices/2005/lifecycle
Content-Type: application/json

{
  "lifecycle_status": "sold",
  "reason": "Sold to XYZ Company on 2026-05-09"
}
```

### Mark a Device as Decommissioned

```bash
PUT /api/devices/3005/lifecycle
Content-Type: application/json

{
  "lifecycle_status": "decommissioned",
  "reason": "Damaged beyond repair during rental"
}
```

---

## Impact on Rental Statistics

### Before Change

If device "2005" has 50 rental records:
- All 50 rentals count toward historical statistics
- Device appears in "active device count"
- Revenue from 50 rentals is included

### After Change (Mark as Sold)

1. **Historical Data:** All 50 rental records remain in database (AUDIT TRAIL PRESERVED)
2. **Current Statistics Calculation:**
   - Device is excluded from active device count
   - New rentals with this device cannot be created
   - Revenue in \`get_periodic_stats()\` excludes this device going forward
3. **Admin Dashboard:** Shows device with \`lifecycle_status: 'sold'\`

---

## Current Exclusion Mechanism (Reference)

**Devices Currently Excluded:**
```
2005, 3005, 3006              # Already marked as broken/decommissioned
代发01, 代发02, 代发03, 代发 04 深圳  # Dropshipping devices
```

These are embedded in code at \`app/routes/rental_stats_api.py\` line 19.

**After Implementation:** These can be moved to database \`lifecycle_status\` field for easier management.

---

## File Locations Reference

| Component | Location | Notes |
|-----------|----------|-------|
| Device Model | app/models/device.py | Core data model |
| Rental Model | app/models/rental.py | Rental records linked to devices |
| Device API | app/routes/device_api.py | REST endpoints for device management |
| Rental Stats API | app/routes/rental_stats_api.py | Statistics calculation (current exclusion logic) |
| Database | Uses SQLAlchemy ORM with PostgreSQL backend |  |
| Migrations | migrations/versions/ | Alembic migration files |

---

## Key Discoveries

1. **Existing Exclusion Mechanism:** The codebase already has a system for excluding devices from statistics using the EXCLUDED_DEVICE_NAMES hardcoded set (devices 2005, 3005, 3006, and several dropshipping devices are already excluded)

2. **Database Structure:** Uses SQLAlchemy ORM with PostgreSQL, supporting Enum types for status fields

3. **Rental Independence:** Devices and Rentals are properly separated - a device can have many rentals. Marking a device as "sold" won't delete its historical rentals

4. **Statistics Calculation:** The rental_stats_api.py has sophisticated calculations for:
   - Device count (active vs total)
   - Rental rates (orders per device)
   - Revenue and profit calculations
   - Depreciation modeling

5. **No Current Lifecycle Field:** The Device model only has a binary \`status\` field (online/offline), not a lifecycle field

---

## Next Steps for Implementation

1. Review the exact requirements for which statuses you need
2. Create a database migration to add lifecycle_status, lifecycle_reason, and lifecycle_date columns
3. Update the Device model class to include new fields
4. Modify the _get_excluded_device_ids_from_db() function to query lifecycle_status
5. Create API endpoint to update device lifecycle status
6. Add UI for marking devices as sold/decommissioned
7. Test statistics calculations to verify devices are properly excluded

