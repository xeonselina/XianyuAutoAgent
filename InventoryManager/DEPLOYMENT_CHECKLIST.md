# Rental Accessory Simplification - Deployment Checklist

## Pre-Deployment

### 1. Code Review
- [ ] Review all modified backend files
- [ ] Review all modified frontend files
- [ ] Review test coverage
- [ ] Check for any TODO comments or placeholder code

### 2. Database Backup
```bash
# Create backup before migration
mysqldump -u [user] -p [database] > backup_before_accessory_migration_$(date +%Y%m%d_%H%M%S).sql
```

### 3. Development Environment Testing
- [ ] Run database migration in dev environment
- [ ] Validate migration with SQL script
- [ ] Run backend unit tests
- [ ] Run backend integration tests
- [ ] Test frontend type conversions
- [ ] Manually test all user flows

---

## Deployment Steps

### Step 1: Backend Deployment

#### 1.1 Database Migration
```bash
# Navigate to project directory
cd /path/to/XianyuAutoAgent/InventoryManager

# Run migration
flask db upgrade

# Validate migration
mysql -u [user] -p [database] < migrations/validate_bundled_accessory_migration.sql
```

**Expected Output:**
- Migration runs without errors
- Validation queries return 0 mismatches
- All columns and indexes created successfully

#### 1.2 Verify Backend Services
```bash
# Restart backend server
flask run

# Check logs for any errors
tail -f logs/app.log
```

### Step 2: Frontend Manual Updates (REQUIRED)

Follow instructions in `frontend/ACCESSORY_UPDATE_INSTRUCTIONS.md`:

#### 2.1 Update BookingDialog.vue
- [ ] Replace multi-select dropdown with checkbox group for bundled accessories
- [ ] Add separate dropdowns for phone holder and tripod
- [ ] Update form state to use new structure
- [ ] Update submit handler to convert UI format to API format

#### 2.2 Update EditRentalDialogNew.vue
- [ ] Add `loadRentalData()` conversion logic
- [ ] Update form state structure
- [ ] Update submit handler

#### 2.3 Build Frontend
```bash
cd frontend
npm run build
```

### Step 3: Deployment Verification

#### 3.1 API Endpoints
```bash
# Test create rental with bundled accessories
curl -X POST http://localhost:5000/api/rentals \
  -H "Content-Type: application/json" \
  -d '{
    "device_id": 1,
    "start_date": "2026-01-10",
    "end_date": "2026-01-15",
    "customer_name": "部署测试",
    "includes_handle": true,
    "includes_lens_mount": true,
    "accessories": []
  }'

# Expected: 201 Created with rental data including includes_handle=true, includes_lens_mount=true
```

#### 3.2 Manual UI Testing
- [ ] Open booking dialog
- [ ] Verify checkbox UI for handle and lens mount
- [ ] Verify dropdown UI for phone holder and tripod
- [ ] Create test rental with bundled accessories
- [ ] Create test rental with inventory accessories
- [ ] Create test rental with mixed accessories
- [ ] Edit existing rental - verify data loads
- [ ] Print shipping slip - verify accessory display
- [ ] View Gantt chart - verify tooltip shows accessories

#### 3.3 Historical Data Verification
```bash
# Query to check historical rentals
mysql -u [user] -p [database] -e "
  SELECT 
    id, 
    customer_name, 
    includes_handle, 
    includes_lens_mount,
    (SELECT COUNT(*) FROM rentals child WHERE child.parent_rental_id = rentals.id) as child_count
  FROM rentals 
  WHERE parent_rental_id IS NULL 
  ORDER BY created_at DESC 
  LIMIT 10;
"
```

- [ ] Verify historical orders display correctly
- [ ] Verify printing works for old orders
- [ ] Verify Gantt chart shows old orders

---

## Post-Deployment Monitoring

### First 24 Hours

#### Monitor Logs
```bash
# Backend errors
tail -f logs/app.log | grep ERROR

# Database queries
tail -f logs/app.log | grep "rental"
```

#### Check Metrics
- [ ] Monitor rental creation success rate
- [ ] Check for any API errors
- [ ] Monitor database query performance
- [ ] Check frontend error logs (browser console)

### Week 1 Checklist
- [ ] Day 1: Intensive monitoring, be ready for rollback
- [ ] Day 3: Review any reported issues
- [ ] Day 7: Analyze usage patterns, verify all flows work

---

## Rollback Plan

If critical issues are discovered:

### Emergency Rollback Steps

#### 1. Revert Code
```bash
# Checkout previous commit
git checkout [previous-commit-hash]

# Rebuild frontend
cd frontend
npm run build

# Restart backend
flask run
```

#### 2. Rollback Database Migration
```bash
# Downgrade to previous migration
flask db downgrade

# Restore from backup if needed
mysql -u [user] -p [database] < backup_before_accessory_migration_[timestamp].sql
```

⚠️ **WARNING**: Downgrade does NOT restore child rental records. Manual data recovery may be required.

#### 3. Verify Rollback
- [ ] Test rental creation
- [ ] Test rental editing
- [ ] Test printing
- [ ] Test Gantt chart

---

## Troubleshooting Guide

### Issue: Migration Fails

**Symptoms:** Migration script throws error

**Solutions:**
1. Check database connection
2. Verify table structure matches expectations
3. Check for locked tables
4. Review migration script for syntax errors

```bash
# Check table structure
DESCRIBE rentals;

# Check for locks
SHOW OPEN TABLES WHERE In_use > 0;
```

### Issue: API Returns 500 Error on Rental Creation

**Symptoms:** POST /api/rentals returns 500

**Solutions:**
1. Check backend logs for detailed error
2. Verify database columns exist
3. Test with minimal payload

```bash
# Check logs
tail -f logs/app.log

# Test minimal payload
curl -X POST http://localhost:5000/api/rentals \
  -H "Content-Type: application/json" \
  -d '{
    "device_id": 1,
    "start_date": "2026-01-10",
    "end_date": "2026-01-15",
    "customer_name": "Test"
  }'
```

### Issue: Frontend Shows Old UI

**Symptoms:** Still shows multi-select dropdown

**Solutions:**
1. Frontend manual updates not applied - see `frontend/ACCESSORY_UPDATE_INSTRUCTIONS.md`
2. Browser cache - clear cache and hard refresh (Ctrl+Shift+R)
3. Build not deployed - rebuild and deploy frontend

```bash
# Clear and rebuild
cd frontend
rm -rf dist/
npm run build
```

### Issue: Historical Data Shows Incorrectly

**Symptoms:** Old rentals missing accessory info

**Solutions:**
1. Run validation SQL to check migration
2. Verify `get_all_accessories_for_display()` works
3. Check child rentals still exist in database

```bash
# Check child rentals exist
mysql -u [user] -p [database] -e "
  SELECT COUNT(*) as child_rental_count 
  FROM rentals 
  WHERE parent_rental_id IS NOT NULL;
"
```

### Issue: Printing Fails

**Symptoms:** Shipping slip generation error

**Solutions:**
1. Check PIL/Pillow library installed
2. Verify `get_all_accessories_for_display()` returns correct format
3. Check logs for specific error

```python
# Test in Python shell
from app import create_app, db
from app.models.rental import Rental

app = create_app()
with app.app_context():
    rental = Rental.query.first()
    accessories = rental.get_all_accessories_for_display()
    print(accessories)
```

---

## Success Criteria

### Deployment is successful when:

- [x] Database migration completes without errors
- [x] All validation queries pass
- [x] Backend tests pass (unit + integration)
- [x] Frontend builds without errors
- [ ] **Manual frontend updates applied** ⚠️
- [ ] UI shows checkboxes for bundled accessories
- [ ] UI shows dropdowns for inventory accessories
- [ ] Rental creation works with new UI
- [ ] Rental editing works with new UI
- [ ] Printing displays all accessories correctly
- [ ] Gantt chart shows accessories with correct markers
- [ ] Historical data displays correctly
- [ ] No critical errors in logs after 24 hours

---

## Contact & Escalation

### If Issues Arise:
1. Check this troubleshooting guide first
2. Review `IMPLEMENTATION_SUMMARY.md` for implementation details
3. Check test files for expected behavior examples
4. Review inline code comments for specific logic

### Emergency Contacts:
- Database Admin: [contact info]
- Backend Lead: [contact info]
- Frontend Lead: [contact info]

---

**Deployment Date:** _____________
**Deployed By:** _____________
**Verification Completed:** _____________
**Sign-off:** _____________
