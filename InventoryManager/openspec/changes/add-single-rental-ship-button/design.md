# Design: Add Single Rental Ship Button

## Architecture Overview

This change adds a new user-facing action to the rental edit dialog, leveraging existing backend services without modifying core business logic.

```
┌─────────────────────────────────────────────────────────────┐
│ Frontend: EditRentalDialogNew.vue                           │
│  ├─ RentalActionButtons.vue                                 │
│  │   └─ [发货到闲鱼] Button (NEW)                            │
│  │       ├─ Validates rental fields                         │
│  │       └─ Calls API: POST /api/rentals/{id}/ship-to-xianyu│
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│ Backend: rental_api.py (NEW ENDPOINT)                       │
│  └─ ship_rental_to_xianyu(rental_id)                        │
│      ├─ Fetch rental by ID                                  │
│      ├─ Validate: has xianyu_order_no & ship_out_tracking_no│
│      ├─ Call XianyuOrderService.ship_order(rental) ──┐      │
│      ├─ Update rental.status = 'shipped' (if success) │      │
│      └─ db.session.commit()                           │      │
└───────────────────────────────────────────────────────┼──────┘
                                                        │
                           ┌────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────┐
│ XianyuOrderService.ship_order(rental) (EXISTING)            │
│  ├─ Validates rental.xianyu_order_no                        │
│  ├─ Validates rental.ship_out_tracking_no                   │
│  ├─ Builds request data                                     │
│  └─ POST /api/open/order/ship to Xianyu API                 │
└─────────────────────────────────────────────────────────────┘
```

## Component Changes

### Frontend: RentalActionButtons.vue
**Location:** `frontend/src/components/rental/RentalActionButtons.vue`

**New Elements:**
```vue
<el-button
  type="primary"
  size="small"
  @click="handleShipToXianyu"
  :disabled="!canShipToXianyu || shippingToXianyu"
  :loading="shippingToXianyu"
>
  <el-icon><Van /></el-icon>
  发货到闲鱼
</el-button>
```

**New Props:**
- None (uses existing `rental` prop)

**New Emits:**
- `ship-to-xianyu`: Emitted when ship button is clicked

**New Computed:**
- `canShipToXianyu`: Returns `true` if rental has both `xianyu_order_no` and `ship_out_tracking_no`

**New State:**
- `shippingToXianyu`: Boolean loading state

### Frontend: EditRentalDialogNew.vue
**Location:** `frontend/src/components/rental/EditRentalDialogNew.vue`

**Changes:**
- Add `@ship-to-xianyu="handleShipToXianyu"` listener to `RentalActionButtons`
- Implement `handleShipToXianyu()` method that calls ganttStore API

### Backend: rental_api.py
**Location:** `app/routes/rental_api.py`

**New Endpoint:**
```python
@bp.route('/api/rentals/<rental_id>/ship-to-xianyu', methods=['POST'])
def ship_rental_to_xianyu(rental_id):
    """
    Ship single rental to Xianyu
    Syncs tracking number via Xianyu API and updates rental status
    """
    return RentalHandlers.handle_ship_rental_to_xianyu(rental_id)
```

### Backend: rental_handlers.py
**Location:** `app/handlers/rental_handlers.py`

**New Handler Method:**
```python
@staticmethod
def handle_ship_rental_to_xianyu(rental_id: str) -> ApiResponse:
    """
    Handle shipping single rental to Xianyu

    Returns:
        ApiResponse with success/failure and message
    """
    # 1. Get rental
    # 2. Validate fields (xianyu_order_no, ship_out_tracking_no)
    # 3. Call xianyu_service.ship_order(rental)
    # 4. Update status to 'shipped' if not already
    # 5. Commit transaction
    # 6. Return response
```

## Data Flow

### Success Flow
1. User clicks "发货到闲鱼" button
2. Frontend validates rental has required fields (client-side check)
3. POST request to `/api/rentals/{rental_id}/ship-to-xianyu`
4. Backend fetches rental record
5. Backend validates rental has `xianyu_order_no` and `ship_out_tracking_no`
6. Backend calls `XianyuOrderService.ship_order(rental)`
7. Xianyu API returns success (code=0)
8. Backend updates `rental.status = 'shipped'` (if not already)
9. Backend commits database transaction
10. Backend returns success response
11. Frontend shows success message
12. Frontend refreshes rental data to show updated status

### Error Flow - Missing Fields
1. User opens edit dialog for rental without `xianyu_order_no`
2. Button is disabled (grayed out)
3. Tooltip shows "缺少闲鱼订单号或快递单号"

### Error Flow - Xianyu API Failure
1. User clicks "发货到闲鱼" button
2. Backend calls Xianyu API
3. Xianyu API returns error (code != 0)
4. Backend does NOT update rental status
5. Backend rolls back transaction
6. Backend returns error response with Xianyu error message
7. Frontend shows error notification

## API Contract

### Request
```
POST /api/rentals/{rental_id}/ship-to-xianyu
Content-Type: application/json

Body: (empty)
```

### Response - Success
```json
{
  "success": true,
  "message": "已成功发货到闲鱼",
  "data": {
    "rental_id": 123,
    "xianyu_order_no": "1234567890",
    "ship_out_tracking_no": "SF1234567890",
    "status": "shipped"
  }
}
```

### Response - Error (Missing Fields)
```json
{
  "success": false,
  "message": "租赁记录缺少闲鱼订单号或快递单号"
}
```

### Response - Error (Xianyu API Failure)
```json
{
  "success": false,
  "message": "闲鱼发货失败: [具体错误信息]"
}
```

## Error Handling

### Frontend Validation
- Button disabled if `!rental.xianyu_order_no || !rental.ship_out_tracking_no`
- Loading state prevents double-clicks
- Error notifications display backend error messages

### Backend Validation
- Return 404 if rental not found
- Return 400 if missing `xianyu_order_no` or `ship_out_tracking_no`
- Return 500 if Xianyu API call fails
- Rollback transaction on any error

### Logging
- INFO: Log successful shipping operations
- ERROR: Log Xianyu API failures with full error details
- Include rental_id in all log messages for traceability

## Security Considerations
- No new authentication/authorization (uses existing rental API auth)
- Validates rental_id is integer to prevent injection
- Does not expose Xianyu API credentials in responses
- Transaction rollback ensures data consistency

## Performance Considerations
- Single database query to fetch rental
- Single Xianyu API call (existing pattern)
- Loading state prevents concurrent requests
- No impact on existing batch shipping performance

## Testing Strategy

### Manual Testing
1. **Happy Path**: Click ship button for rental with all required fields → Success
2. **Missing Order No**: Verify button is disabled when `xianyu_order_no` is empty
3. **Missing Tracking No**: Verify button is disabled when `ship_out_tracking_no` is empty
4. **Already Shipped**: Verify button works even if status is already 'shipped'
5. **API Failure**: Simulate Xianyu API error → Error message displayed

### Edge Cases
- Rental exists but is cancelled → Button should work (up to business logic)
- Multiple rapid clicks → Loading state prevents double submission
- Xianyu returns success but status update fails → Transaction rollback

## Migration & Rollout
- No database migrations required
- No configuration changes required
- Feature is purely additive (no breaking changes)
- Can be deployed without feature flag (low risk)

## Open Questions
None - all design decisions are straightforward based on existing patterns.
