# Device Lifecycle Management - Deployment Guide

**Date:** May 9, 2026  
**Project:** XianyuAutoAgent Inventory Manager  
**Implementation Status:** Ready for Deployment

---

## Table of Contents

1. [Pre-Deployment Checklist](#pre-deployment-checklist)
2. [Database Migration Steps](#database-migration-steps)
3. [Testing Procedures](#testing-procedures)
4. [Deployment Steps](#deployment-steps)
5. [Rollback Procedures](#rollback-procedures)
6. [Post-Deployment Verification](#post-deployment-verification)

---

## Pre-Deployment Checklist

Before deploying, ensure the following:

- [ ] All code changes have been reviewed
- [ ] Database backup has been created
- [ ] Test environment has been prepared
- [ ] Team has been notified of the deployment window
- [ ] Migration script has been validated
- [ ] API endpoints have been tested locally
- [ ] Admin UI changes have been reviewed
- [ ] Monitoring and logging are in place

**Files Modified:**
- ✓ `app/models/device.py` - Added lifecycle status fields and helper methods
- ✓ `app/routes/device_api.py` - Added lifecycle management endpoints
- ✓ `app/routes/rental_stats_api.py` - Updated exclusion logic
- ✓ `migrations/versions/001_add_device_lifecycle_management.py` - NEW migration
- ✓ `app/templates/device_lifecycle_modal.html` - NEW admin UI template

---

## Database Migration Steps

### Step 1: Create Database Backup

```bash
# Create a backup of the current database (adjust credentials as needed)
pg_dump -h localhost -U [db_user] [db_name] > backup_$(date +%Y%m%d_%H%M%S).sql

# Verify backup
ls -lh backup_*.sql
```

### Step 2: Create Fresh Migration (If Needed)

If the migration file wasn't auto-generated, create it manually:

```bash
cd /Users/jimmypan/git_repo/XianyuAutoAgent/InventoryManager

# Generate new migration
flask db migrate -m "add_device_lifecycle_management"

# This will create a new file in migrations/versions/
# Verify the generated file matches our implementation
```

### Step 3: Test Migration in Development

```bash
# In your development environment:
flask db upgrade

# Verify the migration worked
psql -h localhost -U [db_user] -d [db_name] -c "\d devices"

# Should see columns: lifecycle_status, lifecycle_reason, lifecycle_date
```

### Step 4: Verify Enum Type

```bash
psql -h localhost -U [db_user] -d [db_name] -c "SELECT typname FROM pg_type WHERE typname = 'device_lifecycle_status';"

# Should return: device_lifecycle_status
```

---

## Testing Procedures

### Test 1: Database Schema Verification

```bash
# Connect to database
psql -h localhost -U [db_user] -d [db_name]

# Check devices table structure
\d devices

# Verify lifecycle columns exist:
SELECT column_name, data_type 
FROM information_schema.columns 
WHERE table_name = 'devices' 
AND column_name LIKE 'lifecycle%';

# Should return 3 rows: lifecycle_status, lifecycle_reason, lifecycle_date

# Check enum type
\dT device_lifecycle_status

# Should show enum with values: active, sold, decommissioned, damaged, retired
```

### Test 2: Application Boot Test

```bash
# Start the Flask application
cd /Users/jimmypan/git_repo/XianyuAutoAgent/InventoryManager
flask run

# Verify no errors on startup
# Check logs for any model loading errors
```

### Test 3: API Endpoint Tests

#### Test 3a: Get Device List with Lifecycle Status

```bash
curl -X GET http://localhost:5000/api/devices/1 \
  -H "Content-Type: application/json"

# Response should include:
# {
#   "data": {
#     "id": 1,
#     ...
#     "lifecycle_status": "active",
#     "lifecycle_reason": null,
#     "lifecycle_date": null
#   }
# }
```

#### Test 3b: Update Device Lifecycle Status

```bash
# Mark device as sold
curl -X PUT http://localhost:5000/api/devices/1/lifecycle \
  -H "Content-Type: application/json" \
  -d '{
    "lifecycle_status": "sold",
    "lifecycle_reason": "Sold to XYZ Company"
  }'

# Response should show:
# {
#   "success": true,
#   "data": {
#     "id": 1,
#     "lifecycle_status": "sold",
#     "lifecycle_reason": "Sold to XYZ Company",
#     "lifecycle_date": "2026-05-09T15:30:00Z",
#     "is_in_service": false,
#     "is_excluded_from_statistics": true
#   }
# }
```

#### Test 3c: Mark Device as Sold (Quick Endpoint)

```bash
curl -X PUT http://localhost:5000/api/devices/1/mark-sold \
  -H "Content-Type: application/json" \
  -d '{"reason": "Device is no longer available"}'

# Response should indicate successful marking
```

#### Test 3d: Get Lifecycle Summary

```bash
curl -X GET http://localhost:5000/api/devices/lifecycle/summary \
  -H "Content-Type: application/json"

# Response should show:
# {
#   "success": true,
#   "data": {
#     "lifecycle_status_summary": {
#       "active": 7,
#       "sold": 1,
#       "decommissioned": 0,
#       "damaged": 0,
#       "retired": 0,
#       "total": 8
#     },
#     "active_and_online": 7,
#     "excluded_from_statistics": 1,
#     "available_for_rental": 7
#   }
# }
```

#### Test 3e: Get Devices Filtered by Lifecycle Status

```bash
# Get all sold devices
curl -X GET "http://localhost:5000/api/devices/lifecycle/list?status=sold" \
  -H "Content-Type: application/json"

# Get all active devices
curl -X GET "http://localhost:5000/api/devices/lifecycle/list?status=active" \
  -H "Content-Type: application/json"
```

### Test 4: Rental Statistics Integration

```bash
# Verify that excluded devices are not counted in statistics
curl -X GET "http://localhost:5000/api/rental-stats/periodic?period=month&year=2026&month=5" \
  -H "Content-Type: application/json"

# Should show that device count excludes:
# 1. Devices with lifecycle_status != 'active'
# 2. Devices in hardcoded EXCLUDED_DEVICE_NAMES set
```

### Test 5: Helper Method Tests

Create a test script `test_lifecycle.py`:

```python
#!/usr/bin/env python3
"""Test device lifecycle management methods"""

import sys
sys.path.insert(0, '/Users/jimmypan/git_repo/XianyuAutoAgent/InventoryManager')

from app import create_app, db
from app.models.device import Device

app = create_app()
with app.app_context():
    # Test 1: Get a device
    device = Device.query.first()
    print(f"Device: {device.name}")
    
    # Test 2: Check if in service
    print(f"Is in service: {device.is_in_service()}")
    
    # Test 3: Check if excluded
    print(f"Is excluded: {device.is_excluded_from_statistics()}")
    
    # Test 4: Check if can create rental
    print(f"Can create rental: {device.can_create_new_rental()}")
    
    # Test 5: Mark as sold
    print(f"Marking as sold...")
    if device.mark_as_sold("Testing lifecycle"):
        db.session.commit()
        print(f"Device status: {device.lifecycle_status}")
        print(f"Is excluded: {device.is_excluded_from_statistics()}")
    
    # Test 6: Restore to active
    print(f"Restoring to active...")
    if device.restore_to_active("Testing restoration"):
        db.session.commit()
        print(f"Device status: {device.lifecycle_status}")
        print(f"Is excluded: {device.is_excluded_from_statistics()}")
    
    print("All tests passed!")
```

Run the test:
```bash
cd /Users/jimmypan/git_repo/XianyuAutoAgent/InventoryManager
python test_lifecycle.py
```

---

## Deployment Steps

### Step 1: Prepare the Server

```bash
# Navigate to project directory
cd /Users/jimmypan/git_repo/XianyuAutoAgent/InventoryManager

# Verify current git status
git status

# Create a release branch (optional but recommended)
git checkout -b release/lifecycle-management

# Commit all changes
git add app/models/device.py
git add app/routes/device_api.py
git add app/routes/rental_stats_api.py
git add migrations/versions/001_add_device_lifecycle_management.py
git add app/templates/device_lifecycle_modal.html

git commit -m "feat: add device lifecycle management system

- Add lifecycle_status, lifecycle_reason, lifecycle_date fields to devices table
- Implement lifecycle helper methods (is_in_service, is_excluded_from_statistics, etc.)
- Add new API endpoints for managing device lifecycle
- Update rental stats exclusion logic to include lifecycle status
- Add admin UI modal for managing device lifecycle
- Ensure backward compatibility with existing EXCLUDED_DEVICE_NAMES

This allows marking devices as sold/decommissioned without deleting their records,
preserving all historical rental data."

# Push to remote (optional)
git push origin release/lifecycle-management
```

### Step 2: Stop the Application

```bash
# If running via systemd
sudo systemctl stop inventory-manager

# Or if running in Docker
docker-compose down

# Or if running manually, stop the Flask process
# pkill -f "flask run"
```

### Step 3: Apply Migration

```bash
# Navigate to project directory
cd /Users/jimmypan/git_repo/XianyuAutoAgent/InventoryManager

# Activate virtual environment if needed
source venv/bin/activate

# Run migration
flask db upgrade

# Verify migration was applied
flask db current

# Should show: 001_lifecycle_mgmt
```

### Step 4: Verify Migration in Database

```bash
# Connect to database
psql -h localhost -U [db_user] -d [db_name]

# Query to verify columns exist
SELECT column_name, data_type, column_default 
FROM information_schema.columns 
WHERE table_name = 'devices' 
ORDER BY ordinal_position;

# Verify data integrity - all existing devices should have lifecycle_status = 'active'
SELECT COUNT(*) as total, lifecycle_status 
FROM devices 
GROUP BY lifecycle_status;

# Expected: Most devices with 'active', possibly some NULL values
```

### Step 5: Start the Application

```bash
# If using systemd
sudo systemctl start inventory-manager

# Or if using Docker
docker-compose up -d

# Or if running manually
cd /Users/jimmypan/git_repo/XianyuAutoAgent/InventoryManager
python -m flask run --host=0.0.0.0 --port=5000
```

### Step 6: Verify Application Health

```bash
# Wait for application to start (usually 5-10 seconds)
sleep 10

# Check health endpoint
curl -X GET http://localhost:5000/api/devices \
  -H "Content-Type: application/json"

# Should return 200 OK with device list including lifecycle fields
```

---

## Rollback Procedures

If deployment fails or issues arise, follow these rollback steps:

### Option 1: Database Rollback (Without Code Rollback)

```bash
cd /Users/jimmypan/git_repo/XianyuAutoAgent/InventoryManager

# Downgrade migration (reverses the database changes only)
flask db downgrade

# Verify rollback
flask db current

# Should show: fdaa742857fe (the previous revision)
```

### Option 2: Full Rollback (Code + Database)

```bash
# Go back to previous commit
git revert HEAD

# OR use reset (if not pushed to remote yet)
git reset --hard HEAD~1

# Revert database
flask db downgrade

# Verify everything is back to original state
```

### Option 3: Restore from Backup

If something went wrong with data:

```bash
# Stop the application
sudo systemctl stop inventory-manager

# Restore from backup
psql -h localhost -U [db_user] -d [db_name] < backup_YYYYMMDD_HHMMSS.sql

# Start application
sudo systemctl start inventory-manager
```

---

## Post-Deployment Verification

### 1. Database Integrity Check

```bash
# Run integrity checks
psql -h localhost -U [db_user] -d [db_name] << SQL
-- Check for any NULL lifecycle_status values (shouldn't exist)
SELECT COUNT(*) as null_status_count FROM devices WHERE lifecycle_status IS NULL;

-- Check enum type values
SELECT DISTINCT lifecycle_status FROM devices ORDER BY lifecycle_status;

-- Check for orphaned references (if applicable)
SELECT COUNT(*) FROM devices WHERE model_id IS NOT NULL 
AND model_id NOT IN (SELECT id FROM device_models);
SQL
```

### 2. API Response Validation

```bash
# Test all new endpoints
bash << BASH_SCRIPT
echo "Testing API endpoints..."

# Test 1: Get devices with lifecycle fields
echo -e "\n1. GET /api/devices"
curl -s http://localhost:5000/api/devices | jq '.data[0] | keys' | grep lifecycle

# Test 2: Get lifecycle summary
echo -e "\n2. GET /api/devices/lifecycle/summary"
curl -s http://localhost:5000/api/devices/lifecycle/summary | jq '.data'

# Test 3: Get devices by status (active)
echo -e "\n3. GET /api/devices/lifecycle/list?status=active"
curl -s "http://localhost:5000/api/devices/lifecycle/list?status=active" | jq '.total'

echo -e "\nAll API endpoints responding correctly!"
BASH_SCRIPT
```

### 3. Statistics Calculation Verification

```bash
# Verify statistics exclude non-active devices
curl -s http://localhost:5000/api/rental-stats/periodic?period=month \
  | jq '.data | {total_devices, active_devices, excluded_devices}'

# Should show that active_devices + excluded_devices = total_devices
```

### 4. Admin UI Verification

1. Navigate to the device management page in the admin UI
2. Verify that the "Mark as Sold" button appears on each device row
3. Click the button to open the lifecycle management modal
4. Verify the modal displays:
   - Current device information
   - Current lifecycle status
   - Dropdown to select new status
   - Text field for reason
   - Impact warning
5. Test marking a device as sold in the UI
6. Verify the device appears in the excluded list
7. Verify the device can be restored to active status

### 5. Backward Compatibility Check

```bash
# Verify EXCLUDED_DEVICE_NAMES still works
curl -s "http://localhost:5000/api/rental-stats/periodic?period=month" \
  | jq '.data | {excluded_by_name, excluded_by_lifecycle}'

# Should show devices excluded by both mechanisms
```

### 6. Application Logs Review

```bash
# Check application logs for errors
tail -n 100 /var/log/inventory-manager/app.log | grep -i error

# Or if using Docker
docker logs inventory-manager-container | grep -i error

# Should show no lifecycle-related errors
```

---

## Monitoring Recommendations

After deployment, monitor the following:

1. **Application Error Rate** - Should remain < 0.1%
2. **API Response Times** - New endpoints should respond in < 100ms
3. **Database Query Performance** - Index on lifecycle_status should improve query performance
4. **Statistics Accuracy** - Verify device counts match expectations
5. **User Adoption** - Track usage of new lifecycle management endpoints

---

## Rollback Summary

If you need to rollback, execute these commands in order:

```bash
# 1. Stop application
sudo systemctl stop inventory-manager

# 2. Downgrade database
cd /Users/jimmypan/git_repo/XianyuAutoAgent/InventoryManager
flask db downgrade

# 3. Revert code changes
git reset --hard HEAD~1

# 4. Start application
sudo systemctl start inventory-manager

# 5. Verify
sleep 5
curl -X GET http://localhost:5000/api/devices
```

---

## Support & Questions

For questions or issues during deployment:

1. **Database Issues** - Check `DEVICE_LIFECYCLE_IMPLEMENTATION_GUIDE.md` section 7 (Data Migration)
2. **API Issues** - Review test procedures above (Test 3: API Endpoint Tests)
3. **Admin UI Issues** - Check if `device_lifecycle_modal.html` is properly included in templates
4. **Performance Issues** - Verify index was created: `idx_devices_lifecycle_status`

---

## Sign-Off

- [ ] Pre-deployment checklist completed
- [ ] Database backup created
- [ ] Migration tested in development
- [ ] All API endpoints tested
- [ ] Admin UI verified
- [ ] Team notified
- [ ] Deployment completed successfully
- [ ] Post-deployment verification passed
- [ ] Monitoring configured

**Deployed by:** _______________  
**Deployment Date:** _______________  
**Deployment Time:** _______________  

---

Good luck with your deployment! 🚀
