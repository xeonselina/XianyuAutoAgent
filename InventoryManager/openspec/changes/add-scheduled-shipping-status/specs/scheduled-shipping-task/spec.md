# Spec: Scheduled Shipping Task

## Summary

Defines a background task that monitors rentals in `scheduled_for_shipping` status and transitions them to `shipped` when their scheduled time arrives, including Xianyu synchronization.

## ADDED Requirements

### Requirement: A background task MUST execute at regular intervals

A background task MUST run periodically to process rentals that have reached their scheduled ship time.

#### Scenario: Task runs every minute

**GIVEN** the application scheduler is running
**WHEN** the application starts
**THEN** a scheduled task named "process_scheduled_shipments" should be registered
**AND** the task should be configured to run every 1 minute
**AND** the task should be marked as daemon (non-blocking)

#### Scenario: Task executes on schedule

**GIVEN** the scheduled task is registered
**WHEN** 1 minute has elapsed since the last execution
**THEN** the task should execute automatically
**AND** the execution should be logged with timestamp

### Requirement: The task MUST query rentals ready for shipment

The task MUST identify rentals that have reached or passed their scheduled ship time.

#### Scenario: Find rentals due for shipping

**GIVEN** the current time is `2024-01-15 14:30:00`
**AND** rental A has status `'scheduled_for_shipping'` and `scheduled_ship_time = '2024-01-15 14:00:00'`
**AND** rental B has status `'scheduled_for_shipping'` and `scheduled_ship_time = '2024-01-15 14:30:00'`
**AND** rental C has status `'scheduled_for_shipping'` and `scheduled_ship_time = '2024-01-15 15:00:00'`
**WHEN** the task queries for rentals ready to ship
**THEN** rentals A and B should be included in the result
**AND** rental C should be excluded (not yet due)

#### Scenario: Exclude already shipped rentals

**GIVEN** rental D has status `'shipped'` and `scheduled_ship_time = '2024-01-15 13:00:00'`
**WHEN** the task queries for rentals ready to ship
**THEN** rental D should be excluded from the result
**AND** only rentals with status `'scheduled_for_shipping'` should be considered

### Requirement: The task MUST update rental status to shipped

For each rental that is ready to ship, the task MUST update its status and timestamp.

#### Scenario: Successfully transition rental to shipped

**GIVEN** a rental with status `'scheduled_for_shipping'`
**AND** the rental has `scheduled_ship_time = '2024-01-15 14:00:00'`
**AND** the current time is `2024-01-15 14:30:00`
**WHEN** the task processes this rental
**THEN** the rental's status should be updated to `'shipped'`
**AND** the rental's `ship_out_time` should be set to the current timestamp (`2024-01-15 14:30:00`)
**AND** the database transaction should be committed

#### Scenario: Process multiple rentals independently

**GIVEN** rental A and rental B are both ready to ship
**WHEN** the task processes rental A successfully
**AND** processing rental B fails with an exception
**THEN** rental A's status should be `'shipped'` (committed)
**AND** rental B's status should remain `'scheduled_for_shipping'` (transaction rolled back)
**AND** the task should continue execution without stopping

### Requirement: The task MUST synchronize with Xianyu API

For rentals with Xianyu order numbers, the task MUST call the Xianyu ship_order API to notify Xianyu of the shipment.

#### Scenario: Sync to Xianyu when order number exists

**GIVEN** a rental with status `'scheduled_for_shipping'`
**AND** the rental has `xianyu_order_no = 'XY123456'`
**AND** the rental has `ship_out_tracking_no = 'SF3261559084017'`
**WHEN** the task processes this rental
**AND** the rental's status is updated to `'shipped'`
**THEN** the Xianyu ship_order API should be called with:
  - `order_no = 'XY123456'`
  - `waybill_no = 'SF3261559084017'`
  - `express_code = 'shunfeng'`
  - `express_name = '顺丰速运'`
**AND** if the Xianyu API call succeeds, the transaction should commit
**AND** the success should be logged

#### Scenario: Skip Xianyu sync when no order number

**GIVEN** a rental with status `'scheduled_for_shipping'`
**AND** the rental does NOT have `xianyu_order_no` (NULL or empty)
**WHEN** the task processes this rental
**THEN** the rental's status should be updated to `'shipped'`
**AND** the Xianyu ship_order API should NOT be called
**AND** the transaction should commit successfully

### Requirement: The task MUST handle errors gracefully

The task MUST handle errors without crashing and support retry for failed rentals.

#### Scenario: Handle Xianyu API failure

**GIVEN** a rental with status `'scheduled_for_shipping'`
**AND** the rental has a valid `xianyu_order_no`
**WHEN** the task processes this rental
**AND** the Xianyu ship_order API call fails with a network error
**THEN** the error should be logged with rental ID and error details
**AND** the database transaction should be rolled back
**AND** the rental's status should remain `'scheduled_for_shipping'`
**AND** the rental should be retried on the next task execution (1 minute later)

#### Scenario: Handle database errors

**GIVEN** a rental with status `'scheduled_for_shipping'`
**WHEN** the task processes this rental
**AND** the database update fails with a constraint violation
**THEN** the error should be logged with full stack trace
**AND** the transaction should be rolled back
**AND** the task should continue processing other rentals

### Requirement: The task MUST log task execution

The task MUST log its execution for monitoring and debugging.

#### Scenario: Log successful execution

**GIVEN** the task processes 3 rentals successfully
**WHEN** the task completes
**THEN** a log entry should be created with:
  - Task name: "process_scheduled_shipments"
  - Execution timestamp
  - Count of processed rentals: 3
  - Execution duration in seconds
**AND** the log level should be INFO

#### Scenario: Log failures

**GIVEN** the task encounters 2 failures while processing rentals
**WHEN** the task completes
**THEN** error log entries should be created for each failure with:
  - Rental ID
  - Error type and message
  - Full stack trace
**AND** the log level should be ERROR

## MODIFIED Requirements

None - this is a new task implementation.

## REMOVED Requirements

None - no existing scheduled tasks are affected.

## Related Specs

- **rental-status-lifecycle**: Defines the status transition rules implemented by this task
- **batch-print-ui**: Rentals processed by this task become unavailable for printing

## Implementation Notes

### Task Registration

The task should be registered in `app/utils/scheduler.py`:

```python
from app.utils.scheduler_tasks import ScheduledShippingProcessor

processor = ScheduledShippingProcessor()

scheduler.add_job(
    func=processor.process_due_shipments,
    trigger=IntervalTrigger(minutes=1),
    id='process_scheduled_shipments',
    name='Process scheduled shipments',
    replace_existing=True
)
```

### Transaction Isolation

Each rental should be processed in its own transaction:

```python
for rental in due_rentals:
    try:
        # Begin transaction (implicit in Flask-SQLAlchemy)
        rental.status = 'shipped'
        rental.ship_out_time = datetime.utcnow()

        if rental.xianyu_order_no:
            xianyu_service.ship_order(rental)

        db.session.commit()
        logger.info(f"Successfully shipped rental {rental.id}")
    except Exception as e:
        db.session.rollback()
        logger.error(f"Failed to ship rental {rental.id}: {e}")
```

### Query Optimization

Add database index for efficient querying:

```sql
CREATE INDEX idx_rental_scheduled_shipping
ON rentals(status, scheduled_ship_time)
WHERE status = 'scheduled_for_shipping';
```

### Idempotency

The query WHERE clause ensures idempotency:
```python
due_rentals = Rental.query.filter(
    Rental.status == 'scheduled_for_shipping',  # Prevents reprocessing
    Rental.scheduled_ship_time <= datetime.utcnow()
).all()
```

Once status changes to 'shipped', the rental won't be selected again.

## Validation

- [ ] Task is registered and runs every minute
- [ ] Task queries only rentals with status='scheduled_for_shipping' and due time
- [ ] Task updates rental status to 'shipped' correctly
- [ ] Task sets ship_out_time to current timestamp
- [ ] Task calls Xianyu API for rentals with xianyu_order_no
- [ ] Task skips Xianyu API for rentals without xianyu_order_no
- [ ] Failed transactions are rolled back
- [ ] Failed rentals are retried on next execution
- [ ] Task logs execution details and errors
- [ ] Multiple task instances don't run concurrently (file lock)
