# Spec: Rental Status Lifecycle

## Summary

Defines the rental status state machine, including the new `scheduled_for_shipping` status that represents shipments scheduled but not yet physically shipped.

## ADDED Requirements

### Requirement: The system MUST support scheduled_for_shipping status

The system MUST recognize and support a new rental status value `scheduled_for_shipping` that represents orders scheduled for future shipment.

#### Scenario: Rental with scheduled_for_shipping status

**GIVEN** a rental record exists in the database
**WHEN** the rental's status field is set to `'scheduled_for_shipping'`
**THEN** the status should be stored and retrieved correctly
**AND** the rental should have both `ship_out_tracking_no` and `scheduled_ship_time` populated

#### Scenario: Query rentals by scheduled_for_shipping status

**GIVEN** multiple rental records exist with various statuses
**WHEN** querying for rentals with status `'scheduled_for_shipping'`
**THEN** only rentals with that exact status should be returned
**AND** rentals with status `'not_shipped'` or `'shipped'` should be excluded

### Requirement: The system MUST transition from not_shipped to scheduled_for_shipping

When a shipment is scheduled via the batch shipping API, the rental status MUST transition from `not_shipped` to `scheduled_for_shipping`.

#### Scenario: Schedule shipment for not_shipped rental

**GIVEN** a rental with status `'not_shipped'`
**AND** the rental has customer address and device information
**WHEN** scheduling the shipment with a future scheduled time
**AND** the SF Express API successfully generates a waybill number
**THEN** the rental's status should change to `'scheduled_for_shipping'`
**AND** the rental's `ship_out_tracking_no` should be set to the waybill number
**AND** the rental's `scheduled_ship_time` should be set to the requested time
**AND** the rental's `ship_out_time` should remain NULL

#### Scenario: Prevent scheduling already shipped rentals

**GIVEN** a rental with status `'shipped'`
**WHEN** attempting to schedule the shipment
**THEN** the operation should fail with an error message
**AND** the rental's status should remain `'shipped'`

### Requirement: The system MUST transition from scheduled_for_shipping to shipped

When the scheduled ship time arrives, the rental status MUST transition from `scheduled_for_shipping` to `shipped`.

#### Scenario: Transition at scheduled time

**GIVEN** a rental with status `'scheduled_for_shipping'`
**AND** the rental has `scheduled_ship_time` set to `2024-01-15 14:00:00`
**AND** the rental has a valid `ship_out_tracking_no`
**WHEN** the current time reaches or exceeds `2024-01-15 14:00:00`
**AND** the scheduled shipping task runs
**THEN** the rental's status should change to `'shipped'`
**AND** the rental's `ship_out_time` should be set to the current timestamp
**AND** if the rental has `xianyu_order_no`, the Xianyu ship_order API should be called

#### Scenario: Do not transition before scheduled time

**GIVEN** a rental with status `'scheduled_for_shipping'`
**AND** the rental has `scheduled_ship_time` set to `2024-01-15 14:00:00`
**WHEN** the current time is `2024-01-15 13:59:00`
**AND** the scheduled shipping task runs
**THEN** the rental's status should remain `'scheduled_for_shipping'`
**AND** the rental's `ship_out_time` should remain NULL

### Requirement: The frontend MUST display scheduled_for_shipping status in UI

The frontend MUST display the `scheduled_for_shipping` status distinctly from other statuses.

#### Scenario: Show status tag in rental table

**GIVEN** a rental with status `'scheduled_for_shipping'`
**WHEN** viewing the batch shipping page
**THEN** the status column should display a tag labeled "预约发货"
**AND** the tag should have a warning color style (e.g., orange/yellow)
**AND** the tag should be visually distinct from "待发货" (info/gray) and "已发货" (success/green)

## MODIFIED Requirements

None - this is a new status addition to the existing state machine.

## REMOVED Requirements

None - existing status values remain valid.

## Related Specs

- **scheduled-shipping-task**: Implements the transition logic from scheduled_for_shipping to shipped
- **single-waybill-print**: Enables printing for rentals in scheduled_for_shipping status
- **batch-print-ui**: Updated to filter by scheduled_for_shipping status instead of shipped

## Implementation Notes

### Database Migration

The rental status enum must be modified via Alembic migration:

```python
# Migration: Add scheduled_for_shipping status
from alembic import op

def upgrade():
    # For PostgreSQL
    op.execute("ALTER TYPE rental_status ADD VALUE 'scheduled_for_shipping' AFTER 'not_shipped'")

def downgrade():
    # WARNING: PostgreSQL doesn't support removing enum values easily
    # May require recreating the enum type
    pass
```

### Status Enum Order

The new status should be inserted between `not_shipped` and `shipped` to reflect the logical progression:
1. `not_shipped` - Initial state
2. `scheduled_for_shipping` - Scheduled but not shipped
3. `shipped` - Physically shipped
4. `returned` - Returned by customer
5. `completed` - Rental completed
6. `cancelled` - Rental cancelled

## Validation

- [ ] Database accepts `scheduled_for_shipping` as valid status value
- [ ] Queries can filter by `scheduled_for_shipping` status
- [ ] Status transitions follow the defined state machine
- [ ] UI displays the new status correctly
- [ ] API responses include the new status value
