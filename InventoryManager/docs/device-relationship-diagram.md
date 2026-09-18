# Device Data Model - Relationship Diagram

## Entity Relationship Diagram

```
┌─────────────────────────────────────────┐
│         DeviceModel                     │
├─────────────────────────────────────────┤
│ PK  id                                  │
│     name                    (unique)    │
│     display_name                        │
│     is_accessory (bool)                 │
│     parent_model_id (FK) → DeviceModel  │
│     device_value (decimal)              │
│     is_active (bool)                    │
└─────────────────────────────────────────┘
            ▲
            │ 1:N (model_id)
            │
┌─────────────────────────────────────────────────────────────────────────────────┐
│         Device                                                                  │
├─────────────────────────────────────────────────────────────────────────────────┤
│ PK  id                                                                          │
│     name                        (unique device identifier - e.g., "2001")       │
│     serial_number               (unique hardware SN)                            │
│     model                       (e.g., "x200u")                                 │
│ FK  model_id → DeviceModel                                                      │
│     is_accessory                (bool - main device or accessory)               │
│     status                      (Enum: 'online' | 'offline')                    │
│                                                                                 │
│  *** PROPOSED NEW FIELDS ***                                                    │
│  lifecycle_status              (Enum: 'active'|'sold'|'decommissioned'|        │
│                                'damaged'|'retired') DEFAULT='active'            │
│  lifecycle_reason              (varchar 255, optional reason)                   │
│  lifecycle_date                (datetime, when status changed)                  │
│                                                                                 │
│     created_at, updated_at                                                      │
└─────────────────────────────────────────────────────────────────────────────────┘
            ▲
            │ 1:N (device_id)
            │
┌──────────────────────────────────────────────────────────────────────────────────┐
│         Rental                                                                   │
├──────────────────────────────────────────────────────────────────────────────────┤
│ PK  id                                                                           │
│ FK  device_id → Device                                                           │
│     start_date                  (rental period start)                            │
│     end_date                    (rental period end)                              │
│     ship_out_time               (when shipped)                                   │
│     ship_in_time                (when returned)                                  │
│     customer_name                                                                │
│     customer_phone                                                               │
│     destination                                                                  │
│     status                      (Enum: 'not_shipped'|'shipped'|'returned'|      │
│                                'completed'|'cancelled')                          │
│     order_amount                (DECIMAL 10,2)                                   │
│     xianyu_order_no             (optional dropshipping order)                    │
│ FK  parent_rental_id            (self-join for main device + accessories)        │
│     includes_handle             (bool - bundled accessory)                       │
│     includes_lens_mount         (bool - bundled accessory)                       │
│     photo_transfer              (bool - photo relay service)                     │
│     created_at, updated_at                                                       │
└──────────────────────────────────────────────────────────────────────────────────┘
            ▲
            │ 1:N (parent_rental_id - self join)
            │
            └─── Child Rental Records (for accessories)

```

---

## Data Flow for Device Exclusion from Statistics

```
CURRENT STATE (Hardcoded Exclusion):
═══════════════════════════════════

1. Hardcoded list in code:
   EXCLUDED_DEVICE_NAMES = {'2005', '3005', '3006', '代发01', ...}

2. When /api/rental-stats/periodic is called:
   ├─ Query all devices WHERE is_accessory = false
   ├─ Get excluded device IDs by matching device.name against EXCLUDED_DEVICE_NAMES
   └─ Filter: devices NOT IN excluded_ids

3. Calculate statistics only for non-excluded devices:
   ├─ Active device count
   ├─ Rental rate (orders / device count)
   ├─ Revenue calculations
   └─ Depreciation


PROPOSED NEW STATE (Database-Driven Exclusion):
═══════════════════════════════════════════════

1. Admin marks device as sold/decommissioned:
   PUT /api/devices/{id}/lifecycle
   {
     "lifecycle_status": "sold",
     "reason": "Sold to XYZ",
     "lifecycle_date": "2026-05-09"
   }

2. Device.lifecycle_status is updated in database:
   UPDATE devices 
   SET lifecycle_status='sold', 
       lifecycle_reason='...',
       lifecycle_date=NOW()
   WHERE id = {id}

3. When /api/rental-stats/periodic is called:
   ├─ Query all devices WHERE is_accessory = false
   ├─ Get excluded device IDs where lifecycle_status IN 
   │   ('sold', 'decommissioned', 'damaged')
   ├─ Also include legacy EXCLUDED_DEVICE_NAMES for backward compat
   └─ Filter: devices NOT IN excluded_ids

4. Statistics automatically exclude these devices:
   ├─ Device count excludes sold/decommissioned
   ├─ Rental rate calculation unchanged
   ├─ Revenue excludes their rentals going forward
   └─ Historical rental records preserved in database
```

---

## Device Lifecycle State Diagram

```
                    ┌─────────┐
                    │ CREATED │
                    └────┬────┘
                         │
                         ▼
                    ┌─────────┐
             ┌──────┤ ACTIVE  ├──────┐
             │      └─────────┘      │
             │                       │
             ▼                       ▼
        ┌─────────┐            ┌──────────────┐
        │  SOLD   │            │ RETIRED      │
        │(removed)│            │(soft remove) │
        └─────────┘            └──────────────┘
             │                       │
             │      ┌────────────┐   │
             │      │ DAMAGED    │◄──┘
             │      │(needs      │
             │      │repair)     │
             │      └──────┬─────┘
             │             │
             └─────────────┼──────────┐
                          │           │
                          ▼           ▼
                   ┌────────────┐ ┌──────────────┐
                   │DECOMM'ED   │ │(eventually)  │
                   │(removed)   │ │SOLD/RETIRED  │
                   └────────────┘ └──────────────┘

Legend:
- ACTIVE: Device in service, counts toward statistics
- SOLD: Permanently removed from inventory (sold off)
- DECOMMISSIONED: End-of-life/obsolete (permanently removed)
- DAMAGED: Broken/needs repair (temporarily out of service)
- RETIRED: Voluntarily removed from service
```

---

## Statistics Calculation Impact

### Active Device Count Calculation

```
BEFORE: 10 total devices - 3 excluded = 7 active devices

    All Devices (10)
    ├─ 2001 (ACTIVE)      ← counts
    ├─ 2002 (ACTIVE)      ← counts
    ├─ 2003 (ACTIVE)      ← counts
    ├─ 2004 (ACTIVE)      ← counts
    ├─ 2005 (BROKEN)      ← EXCLUDED (hardcoded name match)
    ├─ 3001 (ACTIVE)      ← counts
    ├─ 3002 (ACTIVE)      ← counts
    ├─ 3003 (ACTIVE)      ← counts
    ├─ 3005 (BROKEN)      ← EXCLUDED (hardcoded name match)
    └─ 3006 (BROKEN)      ← EXCLUDED (hardcoded name match)


AFTER with lifecycle_status:

    All Devices (10)
    ├─ 2001 (lifecycle_status='active')           ← counts
    ├─ 2002 (lifecycle_status='active')           ← counts
    ├─ 2003 (lifecycle_status='active')           ← counts
    ├─ 2004 (lifecycle_status='active')           ← counts
    ├─ 2005 (lifecycle_status='decommissioned')   ← EXCLUDED
    ├─ 3001 (lifecycle_status='active')           ← counts
    ├─ 3002 (lifecycle_status='active')           ← counts
    ├─ 3003 (lifecycle_status='active')           ← counts
    ├─ 3005 (lifecycle_status='sold')             ← EXCLUDED
    └─ 3006 (lifecycle_status='decommissioned')   ← EXCLUDED

    Result: Same 7 active devices, but now managed via database!
```

---

## Historical Data Preservation

```
Device "2005" marked as SOLD on 2026-05-09
═══════════════════════════════════════════

devices table:
  id=1005, name='2005', lifecycle_status='sold', lifecycle_date='2026-05-09'

rentals table (ALL records preserved):
  ├─ id=5001, device_id=1005, start='2025-08-01', end='2025-08-03', status='completed'
  ├─ id=5002, device_id=1005, start='2025-08-05', end='2025-08-07', status='completed'
  ├─ id=5003, device_id=1005, start='2025-08-09', end='2025-08-11', status='completed'
  ├─ ... (50 more rental records)
  └─ All historical data remains intact!

Statistics Calculations:
  ├─ HISTORICAL (2025-08): Device 2005 was INCLUDED (lifecycle_status was 'active')
  ├─ HISTORICAL (2025-09): Device 2005 was INCLUDED (lifecycle_status was 'active')
  └─ FUTURE (2026-05+): Device 2005 is EXCLUDED (lifecycle_status='sold')

Result:
  ✓ Historical reports show device contributed to revenue
  ✓ Current reports exclude device from active count
  ✓ No data loss or modification
```

---

## API Integration Points

### 1. Mark Device as Sold

```
PUT /api/devices/2005/lifecycle

Request Body:
{
  "lifecycle_status": "sold",
  "reason": "Sold to customer on 2026-05-09"
}

Response:
{
  "success": true,
  "message": "Device 2005 marked as sold",
  "data": {
    "id": 1005,
    "name": "2005",
    "lifecycle_status": "sold",
    "lifecycle_reason": "Sold to customer on 2026-05-09",
    "lifecycle_date": "2026-05-09T15:30:00Z"
  }
}
```

### 2. Get Device Details (with lifecycle info)

```
GET /api/devices/2005

Response:
{
  "success": true,
  "data": {
    "id": 1005,
    "name": "2005",
    "serial_number": "ABC-123-DEF",
    "model": "x200u",
    "status": "online",
    "lifecycle_status": "sold",                    ← NEW
    "lifecycle_reason": "Sold to customer",        ← NEW
    "lifecycle_date": "2026-05-09T15:30:00Z",      ← NEW
    "created_at": "2025-08-01T00:00:00Z",
    "updated_at": "2026-05-09T15:30:00Z"
  }
}
```

### 3. Statistics Endpoint (auto-excludes)

```
GET /api/rental-stats/periodic?model=x200u&start_date=2025-08-01&end_date=2026-05-09

Response includes:
{
  "success": true,
  "data": [
    {
      "period": "2025-08",
      "device_count": 7,        ← excludes device 2005 (sold on 2026-05-09)
      "order_count": 28,
      "rental_rate": 0.70,
      ...
    }
  ]
}
```

---

## Migration Path

```
Current Implementation (Hardcoded)
│
├─ EXCLUDED_DEVICE_NAMES at line 19 of rental_stats_api.py
├─ No database field for lifecycle management
└─ Changes require code redeploy

                    ▼

New Implementation (Database-Driven)
│
├─ Add 3 new columns to devices table
│  ├─ lifecycle_status (enum)
│  ├─ lifecycle_reason (varchar)
│  └─ lifecycle_date (datetime)
│
├─ Update _get_excluded_device_ids_from_db() to query new field
│
├─ Add API endpoint for marking devices
│  └─ PUT /api/devices/{id}/lifecycle
│
├─ Add Admin UI for device lifecycle management
│
└─ No changes needed to rental records or historical data
```

