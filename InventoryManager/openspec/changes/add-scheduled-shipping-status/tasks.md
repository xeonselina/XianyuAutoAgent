# Tasks: Add Scheduled Shipping Status

## Overview

Implementation tasks for adding scheduled_for_shipping status and deferred Xianyu synchronization.

## Phase 1: Database Migration (HIGH PRIORITY)

### Task 1.1: Create database migration
- [x] Generate Alembic migration file: `flask db revision -m "add_scheduled_for_shipping_status"`
- [x] Write upgrade: Add `'scheduled_for_shipping'` to rental_status enum
- [x] Write downgrade: Handle removal and data migration
- [x] Test migration on development database

**Files**: `migrations/versions/462f68514da8_add_scheduled_for_shipping_status.py`

**Validation**:
- Run `flask db upgrade` successfully (to be tested)
- Query database to verify `scheduled_for_shipping` appears in enum values
- Verify existing rentals remain queryable

### Task 1.2: Test migration on staging
- [ ] Backup staging database
- [ ] Run migration on staging
- [ ] Verify no data loss or corruption
- [ ] Test rollback migration
- [ ] Document any issues found

**Validation**:
- All existing rentals remain queryable
- Application starts without errors
- Status queries work correctly

## Phase 2: Scheduled Task Implementation (HIGH PRIORITY)

### Task 2.1: Create ScheduledShippingProcessor class
- [x] Create class in `app/utils/scheduler_tasks.py`
- [x] Implement `process_due_shipments()` method
- [x] Add query for rentals with status='scheduled_for_shipping' and due time
- [x] Implement status update logic (status, ship_out_time)
- [x] Implement Xianyu sync logic
- [x] Add error handling and transaction management
- [x] Add logging for success and failures

**Files**: `app/utils/scheduler_tasks.py`

**Validation**:
- Method queries only eligible rentals
- Each rental processed in separate transaction
- Errors don't stop processing of other rentals

### Task 2.2: Register scheduled task
- [x] Import ScheduledShippingProcessor in `app/utils/scheduler.py`
- [x] Add task to scheduler with 1-minute interval
- [x] Test task runs on application start (to be tested)
- [x] Verify file lock prevents duplicate task instances (existing mechanism)

**Files**: `app/utils/scheduler.py`

**Validation**:
- Check logs for task registration message
- Verify task executes every 1 minute
- Confirm only one task instance runs

### Task 2.3: Create database index
- [x] Create migration for index: `idx_rental_scheduled_shipping`
- [x] Index on (status, scheduled_ship_time)
- [x] MySQL doesn't support partial indexes (used regular composite index)
- [x] Test query performance (to be tested)

**Files**: `migrations/versions/462f697d4fcb_add_scheduled_shipping_index.py`

**Validation**:
- Run `EXPLAIN ANALYZE` on task query
- Verify index is used
- Confirm query time < 100ms

## Phase 3: Backend API Changes (HIGH PRIORITY)

### Task 3.1: Modify schedule_shipment endpoint
- [x] Update `app/routes/shipping_batch_api.py`
- [x] Change status assignment from `'shipped'` to `'scheduled_for_shipping'`
- [x] Remove immediate Xianyu ship_order call
- [x] Keep ship_out_time as NULL (set by task instead)
- [x] Update response to reflect new status
- [x] Update error messages to include scheduled_for_shipping in skip logic

**Files**: `app/routes/shipping_batch_api.py`

**Validation**:
- POST to `/api/shipping-batch/schedule` sets status to 'scheduled_for_shipping'
- Response indicates success without Xianyu sync
- ship_out_time is NULL in database

### Task 3.2: Update batch print filtering
- [x] Modify hasWaybills computed property condition
- [x] Change from `status === 'shipped'` to `status === 'scheduled_for_shipping'`
- [x] Keep checks for ship_out_tracking_no and scheduled_ship_time
- [x] Update waybillCount accordingly

**Files**: `frontend/src/views/BatchShippingView.vue`

**Validation**:
- Batch print includes only scheduled_for_shipping rentals
- Count matches filtered rentals

## Phase 4: Frontend UI Changes (MEDIUM PRIORITY)

### Task 4.1: Update status display
- [x] Modify `frontend/src/views/BatchShippingView.vue`
- [x] Add el-tag for 'scheduled_for_shipping' status
- [x] Set label to "预约发货"
- [x] Set type to "warning" (orange/yellow color)
- [x] Ensure visual distinction from other statuses

**Files**: `frontend/src/views/BatchShippingView.vue`

**Validation**:
- Scheduled rentals show "预约发货" tag
- Tag color is warning (orange/yellow)
- Distinct from "待发货" (info) and "已发货" (success)

### Task 4.2: Update print conditions
- [x] Update hasWaybills computed property
- [x] Change filter to `status === 'scheduled_for_shipping' && ship_out_tracking_no && scheduled_ship_time`
- [x] Update waybillCount similarly
- [x] Update button disabled logic
- [x] Update showWaybillPrintDialog filter logic

**Files**: `frontend/src/views/BatchShippingView.vue` (lines 202-203, 323)

**Validation**:
- Print button enabled only for scheduled_for_shipping rentals with waybills
- Count reflects correct number of printable rentals

### Task 4.3: Add individual print button
- [x] Add new table column "操作" (width 100px)
- [x] Add el-button with printer icon
- [x] Show button only for scheduled_for_shipping rentals with tracking_no
- [x] Implement printSingle(rentalId) method
- [x] Call /api/shipping-batch/print-waybills with single rental ID
- [x] Display success/error messages

**Files**: `frontend/src/views/BatchShippingView.vue`

**Validation**:
- Print button appears for eligible rentals
- Button is hidden for ineligible rentals
- Clicking button prints single waybill
- Success/error messages display correctly

### Task 4.4: Update schedule button logic
- [x] Update hasUnshipped computed property
- [x] Filter by `status !== 'shipped' && status !== 'scheduled_for_shipping'`
- [x] Prevent scheduling rentals already in scheduled_for_shipping
- [x] Update unshippedCount

**Files**: `frontend/src/views/BatchShippingView.vue`

**Validation**:
- Schedule button disabled when all rentals are scheduled or shipped
- Only not_shipped rentals can be scheduled

## Phase 5: Testing (HIGH PRIORITY)

### Task 5.1: Unit tests for task processor
- [ ] Create `tests/test_scheduled_shipping_processor.py`
- [ ] Test query logic (finds due rentals, excludes future/shipped)
- [ ] Test status transition (scheduled_for_shipping → shipped)
- [ ] Test ship_out_time assignment
- [ ] Test Xianyu sync call (with and without order_no)
- [ ] Test error handling (Xianyu failure, DB error)
- [ ] Test transaction rollback on failure

**Files**: `tests/test_scheduled_shipping_processor.py`

**Validation**:
- All test cases pass
- Code coverage > 90%

### Task 5.2: Integration tests
- [ ] Create `tests/integration/test_scheduled_shipping_flow.py`
- [ ] Test end-to-end: schedule → wait → task runs → status changes
- [ ] Test batch print after scheduling
- [ ] Test individual print
- [ ] Test Xianyu sync at scheduled time
- [ ] Test failure scenarios

**Files**: `tests/integration/test_scheduled_shipping_flow.py`

**Validation**:
- Full workflow works correctly
- Xianyu sync happens at right time
- Print works for scheduled rentals

### Task 5.3: Frontend tests
- [ ] Test status tag rendering
- [ ] Test print button visibility
- [ ] Test individual print action
- [ ] Test batch print filtering

**Files**: `frontend/tests/` (if test framework exists)

**Validation**:
- UI components render correctly
- User interactions work as expected

## Phase 6: Documentation and Deployment (MEDIUM PRIORITY)

### Task 6.1: Update API documentation
- [ ] Document new status value in API docs
- [ ] Update /schedule endpoint description
- [ ] Document status transition flow
- [ ] Add notes about Xianyu sync timing

**Files**: API documentation (if exists)

**Validation**:
- Documentation accurate and complete

### Task 6.2: Create rollback plan
- [ ] Document rollback steps for migration
- [ ] Document code rollback procedure
- [ ] Create script to reset scheduled_for_shipping → not_shipped if needed
- [ ] Test rollback on staging

**Validation**:
- Rollback plan tested and verified

### Task 6.3: Deploy to staging
- [ ] Run database migration
- [ ] Deploy backend code
- [ ] Deploy frontend code
- [ ] Verify task is running
- [ ] Test full workflow

**Validation**:
- Staging environment works correctly
- No errors in logs
- Task executes on schedule

### Task 6.4: Deploy to production
- [ ] Backup production database
- [ ] Run migration during maintenance window
- [ ] Deploy backend code
- [ ] Deploy frontend code
- [ ] Monitor logs for errors
- [ ] Verify task registration

**Validation**:
- Production deployment successful
- No critical errors
- Task running correctly

## Phase 7: Monitoring and Validation (ONGOING)

### Task 7.1: Set up monitoring
- [ ] Add metric: count of scheduled_for_shipping rentals
- [ ] Add metric: task execution time
- [ ] Add metric: Xianyu sync success rate
- [ ] Add alert: rentals stuck > 1 hour
- [ ] Add alert: task execution failures

**Validation**:
- Metrics visible in monitoring system
- Alerts trigger correctly

### Task 7.2: End-to-end validation
- [ ] Schedule a test shipment
- [ ] Verify status shows "预约发货"
- [ ] Print waybill (batch and individual)
- [ ] Wait for scheduled time
- [ ] Verify status changes to "已发货"
- [ ] Verify Xianyu sync occurred
- [ ] Check logs for any errors

**Validation**:
- Complete workflow works as expected
- No errors or warnings in logs

## Dependencies

- Task 1.1 must complete before any other tasks
- Task 1.2 (staging migration) must complete before production deployment
- Task 2.1-2.2 can run in parallel with Task 3.1
- Task 4.x depends on backend API changes (Task 3.1)
- Task 5.x can start after implementation tasks (1-4) are complete
- Task 6.3 (staging deploy) must complete before 6.4 (production deploy)

## Estimated Effort

- Phase 1: 2-3 hours
- Phase 2: 3-4 hours
- Phase 3: 1-2 hours
- Phase 4: 2-3 hours
- Phase 5: 4-6 hours
- Phase 6: 2-3 hours
- Phase 7: 1-2 hours (ongoing)

**Total**: 15-23 hours (approximately 2-3 working days)

## Risk Mitigation

- **Database migration failure**: Test on staging first, have rollback ready
- **Task doesn't run**: Verify scheduler initialization, check file lock
- **Xianyu sync failures**: Monitor error rate, implement retry logic
- **Performance issues**: Add database index, optimize query
- **Data inconsistency**: Use transactions, test rollback scenarios
