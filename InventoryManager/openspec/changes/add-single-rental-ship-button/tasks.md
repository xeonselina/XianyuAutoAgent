# Tasks: Add Single Rental Ship Button

## Frontend Tasks

### Task 1: Add ship button to RentalActionButtons component
- [x] Open `frontend/src/components/rental/RentalActionButtons.vue`
- [x] Import Van icon from element-plus icons
- [x] Add `shippingToXianyu` reactive state variable
- [x] Add computed property `canShipToXianyu` that checks:
  - `rental.xianyu_order_no` exists
  - `rental.ship_out_tracking_no` exists
- [x] Add "发货到闲鱼" button element with:
  - Type: primary
  - Size: small
  - Icon: Van
  - Disabled condition: `!canShipToXianyu || shippingToXianyu`
  - Loading state: `:loading="shippingToXianyu"`
  - Click handler: `handleShipToXianyu`
- [x] Add tooltip for disabled state: "缺少闲鱼订单号或快递单号"
- [x] Position button after "发货单" button in top-actions div

**Validation:**
- Button appears in edit dialog
- Button is disabled when missing required fields
- Tooltip shows on hover when disabled

### Task 2: Implement ship button click handler in RentalActionButtons
- [x] Add `ship-to-xianyu` to emits definition
- [x] Implement `handleShipToXianyu` method that emits `ship-to-xianyu` event

**Validation:**
- Click event is properly emitted to parent

### Task 3: Handle ship event in EditRentalDialogNew component
- [x] Open `frontend/src/components/rental/EditRentalDialogNew.vue`
- [x] Add `@ship-to-xianyu="handleShipToXianyu"` listener to RentalActionButtons
- [x] Implement `handleShipToXianyu` async method that:
  - Shows loading state
  - Calls `ganttStore.shipRentalToXianyu(rental.id)`
  - On success: Shows ElMessage.success("已成功发货到闲鱼")
  - On success: Calls `loadLatestRentalData()` to refresh
  - On error: Shows ElMessage.error with error message
  - Finally: Clears loading state

**Validation:**
- Click triggers API call
- Success/error notifications display correctly
- Rental data refreshes after success

### Task 4: Add shipRentalToXianyu method to gantt store
- [x] Open `frontend/src/stores/gantt.ts`
- [x] Add `shipRentalToXianyu` method that:
  - Accepts `rentalId: number` parameter
  - Makes POST request to `/api/rentals/${rentalId}/ship-to-xianyu`
  - Returns response data
  - Throws error with message on failure
- [x] Call `loadData()` after successful ship to refresh gantt

**Validation:**
- API request is sent with correct URL and method
- Response data is returned
- Errors are properly thrown with message

## Backend Tasks

### Task 5: Add ship-to-xianyu API endpoint
- [x] Open `app/routes/rental_api.py`
- [x] Add new route:
  ```python
  @bp.route('/api/rentals/<rental_id>/ship-to-xianyu', methods=['POST'])
  def ship_rental_to_xianyu(rental_id):
      """Ship single rental to Xianyu"""
      return RentalHandlers.handle_ship_rental_to_xianyu(rental_id)
  ```

**Validation:**
- Endpoint is accessible at `/api/rentals/{id}/ship-to-xianyu`
- Accepts POST method only

### Task 6: Implement handle_ship_rental_to_xianyu handler
- [x] Open `app/handlers/rental_handlers.py`
- [x] Add `handle_ship_rental_to_xianyu` static method that:
  - Fetches rental by ID using `RentalService.get_rental_by_id(rental_id)`
  - Returns 404 if rental not found
  - Validates `rental.xianyu_order_no` exists (return 400 if missing)
  - Validates `rental.ship_out_tracking_no` exists (return 400 if missing)
  - Gets XianyuOrderService instance: `get_xianyu_service()`
  - Calls `xianyu_service.ship_order(rental)`
  - Checks result: if `success=True`:
    - Update `rental.status = 'shipped'` (if not already)
    - Set `rental.ship_out_time = datetime.utcnow()` (if not already set)
    - Commit database transaction
    - Return success response with rental data
  - If `success=False`:
    - Rollback transaction
    - Return error response with Xianyu error message
  - Wrap in try/except for error handling

**Validation:**
- Returns 404 for non-existent rental
- Returns 400 for missing required fields
- Successfully calls Xianyu API
- Updates rental status on success
- Rolls back transaction on failure

### Task 7: Add logging for ship operations
- [x] In `handle_ship_rental_to_xianyu`, add logging:
  - INFO: "单个发货到闲鱼: Rental {rental_id}, Order {xianyu_order_no}"
  - INFO on success: "单个发货成功: Rental {rental_id}"
  - ERROR on failure: "单个发货失败: Rental {rental_id}, 错误: {error_message}"
  - Include full traceback in ERROR logs

**Validation:**
- Logs appear in application logs
- Logs contain rental_id for traceability
- Error logs include detailed error information

## Testing Tasks

### Task 8: Manual testing - Happy path
- [ ] Create or find a rental with both `xianyu_order_no` and `ship_out_tracking_no`
- [ ] Open edit dialog for this rental
- [ ] Verify "发货到闲鱼" button is enabled
- [ ] Click the button
- [ ] Verify loading spinner appears
- [ ] Verify success notification shows
- [ ] Verify rental status updates to "shipped" in the dialog
- [ ] Check backend logs for success message

**Pass Criteria:**
- Button works and syncs successfully to Xianyu
- Status updates correctly
- Logs show successful operation

### Task 9: Manual testing - Missing fields
- [ ] Create or find a rental without `xianyu_order_no`
- [ ] Open edit dialog
- [ ] Verify "发货到闲鱼" button is disabled (grayed out)
- [ ] Hover over button and verify tooltip shows
- [ ] Add `xianyu_order_no` but leave `ship_out_tracking_no` empty
- [ ] Verify button is still disabled

**Pass Criteria:**
- Button is disabled when missing either field
- Tooltip provides helpful guidance

### Task 10: Manual testing - API error handling
- [ ] Find a rental with `xianyu_order_no` and `ship_out_tracking_no`
- [ ] Temporarily disable Xianyu API (e.g., set wrong credentials in .env)
- [ ] Open edit dialog and click "发货到闲鱼" button
- [ ] Verify error notification displays with clear error message
- [ ] Verify rental status does NOT change
- [ ] Check backend logs for error details
- [ ] Re-enable Xianyu API and verify it works again

**Pass Criteria:**
- Error is handled gracefully
- User sees helpful error message
- Status is not modified on error

### Task 11: Manual testing - Loading state and double-click prevention
- [ ] Add artificial delay to Xianyu API call (optional, for easier testing)
- [ ] Open edit dialog and click "发货到闲鱼" button
- [ ] Immediately try to click button again
- [ ] Verify second click is ignored (button is disabled during API call)
- [ ] Verify loading spinner is visible during API call
- [ ] Verify button re-enables after API completes

**Pass Criteria:**
- Loading state prevents double submission
- Button visual feedback is clear

## Documentation Tasks

### Task 12: Update user documentation (if exists)
- [x] Check if there's user documentation for rental management
- [x] Add note about new "发货到闲鱼" button in edit dialog
- [x] Describe when button is available (requires both order no and tracking no)

**Pass Criteria:**
- Documentation reflects new feature
- OR: Skip if no user docs exist ✓ (No user docs exist, skipped)

## Completion Checklist

Before marking this change as complete:
- [x] All frontend tasks completed
- [x] All backend tasks completed
- [ ] All manual testing passed (requires manual verification by user)
- [ ] No console errors in browser (requires manual verification by user)
- [ ] No server errors in logs (requires manual verification by user)
- [x] Code follows project conventions
- [ ] Feature works in production-like environment (Docker) (requires manual verification by user)
