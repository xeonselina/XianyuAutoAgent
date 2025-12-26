# Proposal: Add Scheduled Shipping Status

## Overview

Introduce a new "scheduled_for_shipping" rental status to decouple the scheduling action from the shipped state, enabling users to schedule shipments and print waybills before the actual ship time, while deferring Xianyu synchronization until the scheduled time arrives.

## Problem Statement

Currently, when users schedule a shipment via the batch shipping interface:
1. The rental status immediately changes to "shipped"
2. Xianyu is notified immediately
3. Users cannot distinguish between "scheduled but not yet shipped" vs "actually shipped"
4. The business process doesn't align with the actual physical shipping timeline

This creates confusion and incorrect status reporting, as items marked "shipped" haven't actually left the warehouse yet.

## Proposed Solution

Add a new rental status: `scheduled_for_shipping` that represents orders that have:
- Been scheduled for shipment at a future time
- Had waybill numbers generated via SF Express API
- Not yet been physically shipped

### Status Flow

```
not_shipped → scheduled_for_shipping → shipped → returned → completed
                   ↑                        ↑
                   |                        |
            (user schedules)         (scheduled time arrives)
```

### Key Changes

1. **Database**: Add `scheduled_for_shipping` to rental status enum
2. **Scheduling Flow**: When users click "预约发货":
   - Call SF Express API to generate waybill
   - Save waybill number to `ship_out_tracking_no`
   - Save scheduled time to `scheduled_ship_time`
   - Set status to `scheduled_for_shipping`
   - Do NOT call Xianyu API yet

3. **Printing**: Enable printing for rentals with status `scheduled_for_shipping` that have both `ship_out_tracking_no` and `scheduled_ship_time`

4. **Individual Print**: Add ability to print single waybill from batch shipping page

5. **Scheduled Task**: Create background job that:
   - Runs every minute
   - Finds rentals with status `scheduled_for_shipping` and `scheduled_ship_time <= now`
   - Updates status to `shipped`
   - Sets `ship_out_time` to current time
   - Calls Xianyu API to sync shipping info

## Benefits

- **Accurate Status Tracking**: Status reflects actual business state
- **Flexible Scheduling**: Users can schedule ahead without misleading status
- **Reliable Xianyu Sync**: Notifications sent at the right time
- **Better Workflow**: Aligns system state with physical operations

## Requirements Addressed

From user request:
1. ✅ 预约发货后rental状态变为"预约发货"
2. ✅ 用户可以在批量发货页面打印所有"预约发货"且有预约时间的面单
3. ✅ 用户可以在批量发货页面挑选其中一个rental单独打印这一单的面单
4. ✅ 到达预约时间后,定时任务将预约发货状态改为已发货,并将快递信息调用闲鱼接口同步到闲鱼

## Scope

This change creates new capabilities for scheduled shipping workflow:
- **rental-status-lifecycle**: Rental status state machine
- **scheduled-shipping-task**: Background job for transitioning scheduled shipments
- **single-waybill-print**: Individual waybill printing UI

## Dependencies

- Requires database migration to modify rental status enum
- Depends on existing SF Express API integration
- Depends on existing Xianyu API integration
- Depends on existing APScheduler infrastructure

## Out of Scope

- Notification system for failed shipments
- Cancellation of scheduled shipments
- Bulk status transitions
- Historical status tracking/audit trail

## Risks and Mitigations

**Risk**: Database migration may fail on production
- **Mitigation**: Test migration on staging with production data copy, create rollback script

**Risk**: Scheduled task might process the same rental multiple times
- **Mitigation**: Use database transaction with status check in WHERE clause

**Risk**: Xianyu API failures at scheduled time
- **Mitigation**: Log failures, keep status as `scheduled_for_shipping`, retry on next run

## Validation Criteria

- [ ] Database migration succeeds without data loss
- [ ] Scheduled shipments show correct status in UI
- [ ] Batch print includes only scheduled_for_shipping rentals
- [ ] Individual print works for single rental
- [ ] Scheduled task transitions status at correct time
- [ ] Xianyu sync happens exactly once per rental
- [ ] Failed Xianyu syncs are retried on subsequent runs
- [ ] All existing flows (non-scheduled) continue to work
