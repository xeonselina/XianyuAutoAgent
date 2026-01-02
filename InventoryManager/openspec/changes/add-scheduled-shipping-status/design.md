# Design: Add Scheduled Shipping Status

## Architecture Overview

This change modifies the batch shipping workflow to introduce an intermediate status between "not_shipped" and "shipped", enabling deferred Xianyu synchronization via a scheduled background task.

## Component Changes

### 1. Database Layer

**File**: `app/models/rental.py`

**Change**: Modify rental status enum to include `scheduled_for_shipping`

```python
status = db.Column(
    db.Enum('not_shipped', 'scheduled_for_shipping', 'shipped', 'returned', 'completed', 'cancelled', name='rental_status'),
    default='not_shipped',
    comment='租赁状态'
)
```

**Migration**: Requires Alembic migration to ALTER TYPE
- Add new enum value
- Verify no existing data violates constraints
- Create rollback migration

### 2. Batch Scheduling API

**File**: `app/routes/shipping_batch_api.py`

**Endpoint**: `POST /api/shipping-batch/schedule`

**Current Behavior**:
```python
# After SF API call succeeds
rental.status = 'shipped'
rental.ship_out_time = datetime.utcnow()
xianyu_service.ship_order(rental)  # Called immediately
```

**New Behavior**:
```python
# After SF API call succeeds
rental.status = 'scheduled_for_shipping'
rental.scheduled_ship_time = scheduled_time
rental.ship_out_time = None  # Will be set by scheduled task
# Do NOT call xianyu_service.ship_order() here
```

**Implications**:
- Removes immediate Xianyu sync
- Sets status to intermediate state
- Leaves `ship_out_time` empty until actual ship time

### 3. Scheduled Task System

**File**: `app/utils/scheduler_tasks.py`

**New Class**: `ScheduledShippingProcessor`

```python
class ScheduledShippingProcessor:
    """Process scheduled shipments that have reached their ship time"""

    def process_due_shipments(self):
        """Find and process rentals ready to ship"""
        now = datetime.utcnow()

        # Find rentals scheduled for shipping
        due_rentals = Rental.query.filter(
            Rental.status == 'scheduled_for_shipping',
            Rental.scheduled_ship_time <= now
        ).all()

        for rental in due_rentals:
            try:
                # Update status
                rental.status = 'shipped'
                rental.ship_out_time = now

                # Sync to Xianyu
                if rental.xianyu_order_no:
                    xianyu_service.ship_order(rental)

                db.session.commit()
            except Exception as e:
                logger.error(f"Failed to process rental {rental.id}: {e}")
                db.session.rollback()
```

**Scheduler Registration** (`app/utils/scheduler.py`):
```python
from app.utils.scheduler_tasks import process_scheduled_shipments

scheduler.add_job(
    func=process_scheduled_shipments,
    trigger=IntervalTrigger(minutes=1),
    id='process_scheduled_shipments',
    name='Process scheduled shipments',
    replace_existing=True
)
```

**Design Decisions**:
- **1-minute interval**: Balances responsiveness vs overhead
- **Transaction per rental**: Prevents one failure from blocking others
- **Idempotent**: Safe to run multiple times (status check in WHERE clause)
- **Retry on failure**: Failed rentals remain in `scheduled_for_shipping` state

### 4. Frontend UI

**File**: `frontend/src/views/BatchShippingView.vue`

#### 4.1 Status Display

Update table column to show new status:
```vue
<el-table-column label="状态" width="80">
  <template #default="{ row }">
    <el-tag v-if="row.status === 'shipped'" type="success">已发货</el-tag>
    <el-tag v-else-if="row.status === 'scheduled_for_shipping'" type="warning">预约发货</el-tag>
    <el-tag v-else type="info">待发货</el-tag>
  </template>
</el-table-column>
```

#### 4.2 Print Condition

Update computed properties:
```javascript
// For batch printing
const hasWaybills = computed(() =>
  rentals.value.some(r =>
    r.status === 'scheduled_for_shipping' &&
    r.ship_out_tracking_no &&
    r.scheduled_ship_time
  )
)

const waybillCount = computed(() =>
  rentals.value.filter(r =>
    r.status === 'scheduled_for_shipping' &&
    r.ship_out_tracking_no &&
    r.scheduled_ship_time
  ).length
)
```

#### 4.3 Individual Print

Add new column with print action button:
```vue
<el-table-column label="操作" width="100">
  <template #default="{ row }">
    <el-button
      v-if="row.status === 'scheduled_for_shipping' && row.ship_out_tracking_no"
      @click="printSingle(row.id)"
      type="primary"
      size="small"
      link
    >
      <el-icon><Printer /></el-icon>
      打印
    </el-button>
  </template>
</el-table-column>
```

**New Method**:
```javascript
const printSingle = async (rentalId: number) => {
  try {
    const response = await axios.post('/api/shipping-batch/print-waybills', {
      rental_ids: [rentalId]
    })

    if (response.data.success) {
      ElMessage.success('面单打印成功')
    }
  } catch (error) {
    ElMessage.error('打印失败')
  }
}
```

### 5. API Routes

**New/Modified Endpoints**:

No new endpoints needed. Existing `/api/shipping-batch/print-waybills` already accepts `rental_ids` array, works for both single and batch.

## Data Flow

### Scheduling Flow (User Action)

```
User selects rentals + scheduled time
         ↓
POST /api/shipping-batch/schedule
         ↓
SF Express API (create order)
         ↓
Save waybill_no, scheduled_ship_time
         ↓
Set status = 'scheduled_for_shipping'
         ↓
Return success to frontend
         ↓
UI shows "预约发货" status
```

### Printing Flow (User Action)

```
User clicks "批量打印快递面单" or individual "打印" button
         ↓
POST /api/shipping-batch/print-waybills
  with rental_ids (array of 1 or more)
         ↓
Query rentals by IDs
         ↓
For each rental:
  - Get waybill_no
  - Call Kuaimai API to print
         ↓
Return success/failure results
```

### Scheduled Ship Flow (Background Task)

```
Cron: Every 1 minute
         ↓
Query rentals WHERE status='scheduled_for_shipping'
  AND scheduled_ship_time <= now
         ↓
For each rental:
  ├── Begin transaction
  ├── Update status = 'shipped'
  ├── Set ship_out_time = now
  ├── Call Xianyu API (if has xianyu_order_no)
  ├── Commit transaction
  └── Log result
```

## Error Handling

### Xianyu Sync Failures

**Scenario**: Xianyu API fails during scheduled task

**Strategy**:
- Log error with rental ID and details
- Rollback transaction (keeps status as `scheduled_for_shipping`)
- Retry on next task run (1 minute later)
- Manual intervention if failures persist

**Alternative Considered**: Move to separate "failed" status
- **Rejected**: Adds complexity, retry is sufficient for transient errors

### Database Migration Risks

**Scenario**: Migration fails to add enum value

**Mitigation**:
1. Test on staging with production data snapshot
2. Backup database before migration
3. Create rollback migration that:
   - Updates any `scheduled_for_shipping` → `not_shipped`
   - Removes enum value
   - Restores original enum

**Rollback Command**:
```bash
flask db downgrade -1
```

### Race Conditions

**Scenario**: User schedules, task runs before DB commit

**Prevention**: Transaction isolation
- Schedule API uses transaction
- Task uses separate transaction with explicit status check

**Scenario**: Multiple task instances process same rental

**Prevention**: File lock in scheduler ensures single instance
- Already implemented in `app/utils/scheduler.py` (lines 43-71)

## Performance Considerations

### Task Frequency

**1-minute interval chosen because**:
- Users expect shipments to transition near scheduled time
- Low query overhead (indexed WHERE on status + timestamp)
- Manageable Xianyu API load (typically < 10 orders/minute)

**Query Optimization**:
```sql
CREATE INDEX idx_rental_scheduled_shipping
ON rentals(status, scheduled_ship_time)
WHERE status = 'scheduled_for_shipping';
```

### Scalability

**Current Load**: ~20-50 shipments/day
**Projected Load**: ~100-200 shipments/day

**Bottleneck Analysis**:
- Xianyu API: Rate limit unknown, sequential calls acceptable
- Database: Indexed query + small result set, no concern
- Task execution: ~1-2 seconds typical, well within 1-minute window

## Testing Strategy

### Unit Tests

1. `test_rental_status_enum.py`: Verify new enum value accepted
2. `test_scheduled_shipping_processor.py`: Test task logic
3. `test_schedule_api_no_xianyu_sync.py`: Verify Xianyu NOT called

### Integration Tests

1. End-to-end scheduling flow
2. Scheduled task transitions status correctly
3. Xianyu sync happens at scheduled time
4. Print works for scheduled_for_shipping status

### Migration Tests

1. Upgrade: Add enum value
2. Data integrity: Existing records unaffected
3. Downgrade: Remove enum value, update data

## Rollout Plan

### Phase 1: Database Migration
1. Test migration on staging
2. Backup production DB
3. Run migration in maintenance window
4. Verify enum value added

### Phase 2: Deploy Backend
1. Deploy scheduler task code
2. Deploy API changes
3. Verify task is running (check logs)

### Phase 3: Deploy Frontend
1. Deploy UI changes
2. Test scheduling flow
3. Monitor for errors

### Phase 4: Validation
1. Schedule test shipment
2. Verify status shows "预约发货"
3. Print waybill
4. Wait for scheduled time
5. Verify status changes to "已发货"
6. Verify Xianyu sync occurred

## Monitoring

**Key Metrics**:
- Count of rentals in `scheduled_for_shipping` status
- Task execution time
- Xianyu sync success rate
- Failed rentals (remain in scheduled_for_shipping after retry)

**Alerts**:
- Task execution failures
- Rentals stuck in scheduled_for_shipping > 1 hour
- Xianyu sync failure rate > 10%

## Open Questions

None - requirements are clear from user request.
