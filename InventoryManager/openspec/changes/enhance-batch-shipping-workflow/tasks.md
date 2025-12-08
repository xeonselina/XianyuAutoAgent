# Tasks

## 1. Database Migration

- [ ] **1.1 Create migration script**
  - Use `flask db revision -m "add_scheduled_shipping_fields"`
  - Add `scheduled_ship_time` (DateTime, nullable) to `rentals` table
  - Add `sf_waybill_no` (String(50), nullable) to `rentals` table
  - Test rollback with `flask db downgrade`
  - Verify: Run migration on dev database

- [ ] **1.2 Update Rental model**
  - Edit `app/models/rental.py`
  - Add `scheduled_ship_time` field
  - Add `sf_waybill_no` field
  - Update `to_dict()` to include new fields
  - Verify: Model tests pass

## 2. Shipping Order QR Code

- [ ] **2.1 Add QR code to shipping order template**
  - Edit `templates/shipping_order2.html` (or create if using new template)
  - Add QR code in top-right corner with rental ID
  - Use `qrcode.js` or server-side Python `qrcode` library
  - Position: absolute top-right, size 80x80px
  - Verify: Print preview shows QR code correctly

- [ ] **2.2 Test QR code scanning**
  - Use phone camera or scanner app to verify QR decodes to rental ID
  - Test with barcode scanner gun
  - Verify: Scanner outputs rental ID correctly

## 3. Batch Shipping Page (Frontend)

- [ ] **3.1 Create BatchShippingView.vue**
  - Create `frontend/src/views/BatchShippingView.vue`
  - Date range picker (start_date, end_date)
  - "预览订单" button to fetch rentals
  - Order list table with columns: rental ID, customer, device, status, waybill
  - Status badges: 未打印/已打印/已录入运单/已发货
  - Verify: Page loads and displays date picker

- [ ] **3.2 Implement order preview**
  - Call `GET /api/rentals/by-ship-date` API
  - Display orders in table
  - Show count of orders in each status
  - Add loading spinner
  - Verify: Orders load correctly for date range

- [ ] **3.3 Add barcode scanner input handler**
  - Listen to keyboard input events (scanner acts as keyboard)
  - Detect pattern: rental ID (digits) vs SF waybill (alphanumeric)
  - Use debounce to detect end of scan (e.g., 200ms timeout)
  - Parse scanned value and trigger appropriate action
  - Verify: Console logs scanned values correctly

- [ ] **3.4 Implement rental QR scan flow**
  - When rental ID scanned, call `POST /api/shipping-batch/scan-rental`
  - Display dialog with rental details (address, phone, device, accessories, dates)
  - Auto-focus dialog (prevent background interaction)
  - Verify: Dialog shows correct rental information

- [ ] **3.5 Implement waybill scan flow**
  - After rental scanned, prompt for SF waybill
  - When waybill scanned, call `POST /api/shipping-batch/record-waybill`
  - Update order status in table
  - Close dialog automatically
  - Play success sound or voice "已录入"
  - Verify: Waybill recorded successfully

- [ ] **3.6 Add voice prompt**
  - Use Web Speech API (`window.speechSynthesis`)
  - Play "请扫描顺丰面单" after rental scan
  - Play "已录入" after waybill scan
  - Add settings to enable/disable voice
  - Verify: Voice plays in Chrome/Safari

- [ ] **3.7 Add schedule shipping dialog**
  - "预约发货" button (only enabled if orders have waybills)
  - Dialog with datetime picker, default = now + 1 hour
  - Show count of orders to be scheduled
  - Call `POST /api/shipping-batch/schedule`
  - Verify: Scheduled time saved correctly

- [ ] **3.8 Add print all button**
  - "批量打印发货单" button
  - Reuse existing `BatchShippingOrderView` route
  - Pass selected rental IDs or date range
  - Verify: Navigates to print view correctly

## 4. Backend API Endpoints

- [ ] **4.1 Create shipping_batch_api.py**
  - Create `app/routes/shipping_batch_api.py`
  - Register blueprint in `app/__init__.py`
  - Add CORS config if needed
  - Verify: Blueprint loaded successfully

- [ ] **4.2 POST /api/shipping-batch/scan-rental**
  - Accept `rental_id` in JSON body
  - Query rental with device, accessories, customer info
  - Return rental details JSON
  - Handle not found error (404)
  - Verify: Postman test returns rental details

- [ ] **4.3 POST /api/shipping-batch/record-waybill**
  - Accept `rental_id`, `waybill_no` in JSON body
  - Update `rental.sf_waybill_no`
  - Validate waybill format (alphanumeric, 10+ chars)
  - Return success/error
  - Verify: Database updated correctly

- [ ] **4.4 POST /api/shipping-batch/schedule**
  - Accept `rental_ids[]`, `scheduled_time` in JSON body
  - Update `rental.scheduled_ship_time` for each rental
  - Validate: only update rentals with `sf_waybill_no`
  - Return count of scheduled rentals
  - Verify: Database updated, scheduler picks up

- [ ] **4.5 GET /api/shipping-batch/status**
  - Accept date range or rental IDs
  - Return status summary: total, printed, waybill_recorded, scheduled, shipped
  - Verify: Returns correct counts

## 5. SF Express API Integration

- [ ] **5.1 Extend sf_express_api.py**
  - Add OAuth2 authentication flow (ref: `docs/顺丰oauth2鉴权.docx`)
  - Implement `create_order()` method (ref: `docs/速运API.docx`)
  - Parse order creation response
  - Handle errors and retries
  - Verify: Test order creation in sandbox mode

- [ ] **5.2 Create SFExpressService**
  - Create `app/services/shipping/sf_express_service.py`
  - Wrapper for `sf_express_api.py`
  - Load credentials from environment variables
  - Implement `place_shipping_order(rental)` method
  - Map rental data to SF API format
  - Verify: Service layer unit tests

- [ ] **5.3 Add error handling**
  - Retry logic (max 3 retries with exponential backoff)
  - Log API errors to database or file
  - Return detailed error messages
  - Verify: Handles network errors gracefully

## 6. Xianyu API Integration

- [ ] **6.1 Create xianyu_api_service.py**
  - Create `app/services/shipping/xianyu_api_service.py`
  - Implement signature generation (ref: `docs/闲鱼管家 api 文档.md`)
  - Implement `ship_order()` method (POST /api/open/order/ship)
  - Load appid, seller_id, secret from env
  - Verify: Signature matches expected format

- [ ] **6.2 Map rental to Xianyu ship request**
  - Extract `xianyu_order_no`, `waybill_no`, `express_code`, `express_name`
  - Use hardcoded sender info or from config
  - Handle missing order_no gracefully
  - Verify: Request format matches API spec

- [ ] **6.3 Add error handling**
  - Parse Xianyu error responses (code != 0)
  - Retry on network errors
  - Log failures for manual intervention
  - Verify: Handles API errors correctly

## 7. Scheduled Shipping Task

- [ ] **7.1 Create scheduler_shipping_task.py**
  - Create `app/services/shipping/scheduler_shipping_task.py`
  - Query rentals with `scheduled_ship_time <= now` and `status != 'shipped'`
  - For each rental:
    - Call SF Express API to create order
    - Call Xianyu API to notify shipping
    - Update `status = 'shipped'`, `ship_out_time = now`
  - Verify: Function runs successfully

- [ ] **7.2 Integrate with APScheduler**
  - Add task to `app/utils/scheduler_tasks.py`
  - Schedule every 5 minutes
  - Use `misfire_grace_time` to handle server restarts
  - Verify: Scheduler executes task

- [ ] **7.3 Add logging and monitoring**
  - Log each rental processed
  - Log API call results (success/failure)
  - Email alert on multiple failures (optional)
  - Verify: Logs visible in console/file

## 8. UI Updates

- [ ] **8.1 Update GanttChart button**
  - Edit `frontend/src/components/GanttChart.vue`
  - Change button text from "批量打印发货单" to "批量发货"
  - Update route to `/batch-shipping` (new page)
  - Verify: Button text and route updated

- [ ] **8.2 Add BatchShippingView route**
  - Edit `frontend/src/router/index.ts`
  - Add route: `/batch-shipping` -> `BatchShippingView`
  - Verify: Route resolves correctly

- [ ] **8.3 Update BatchShippingOrderView**
  - Edit `frontend/src/views/BatchShippingOrderView.vue`
  - Ensure compatibility with new workflow (called from BatchShippingView)
  - Verify: Print view still works

## 9. Testing

- [ ] **9.1 Unit tests**
  - Test rental model fields
  - Test API signature generation
  - Test waybill format validation
  - Test scheduler task logic
  - Verify: All unit tests pass

- [ ] **9.2 Integration tests**
  - Test full scan workflow (rental → waybill → schedule)
  - Test API endpoints with mock data
  - Test scheduler task with mock time
  - Verify: Integration tests pass

- [ ] **9.3 Manual testing**
  - Test with real barcode scanner
  - Test QR code scanning with phone
  - Test voice prompts in browser
  - Test scheduled shipping (set time 1 min in future)
  - Test SF API in sandbox mode
  - Verify: All manual tests successful

- [ ] **9.4 Error scenario testing**
  - Scan invalid rental ID
  - Scan duplicate waybill
  - SF API returns error
  - Xianyu API returns error
  - Scheduler runs when rentals already shipped
  - Verify: Errors handled gracefully

## 10. Documentation

- [ ] **10.1 Update user documentation**
  - Document new batch shipping workflow
  - Add screenshots of BatchShippingView
  - Explain QR code scanning process
  - Document error scenarios and solutions
  - Verify: Documentation complete

- [ ] **10.2 Update API documentation**
  - Document new API endpoints
  - Add request/response examples
  - Document authentication requirements
  - Verify: API docs accurate

- [ ] **10.3 Add deployment notes**
  - Document required environment variables (SF, Xianyu credentials)
  - Document database migration steps
  - Document scheduler configuration
  - Verify: Deployment runbook complete

## Dependencies

- Task 3 depends on Task 4 (API endpoints)
- Task 7 depends on Task 5 and 6 (API integrations)
- Task 8 depends on Task 3 (UI implementation)
- Task 9 depends on all previous tasks

## Parallelizable Work

- Task 2 (QR code) and Task 4 (API) can be developed in parallel
- Task 5 (SF API) and Task 6 (Xianyu API) can be developed in parallel
- Task 3 (Frontend) can start after Task 4 APIs are stubbed
