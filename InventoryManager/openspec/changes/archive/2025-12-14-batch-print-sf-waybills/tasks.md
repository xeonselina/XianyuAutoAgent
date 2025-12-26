# Tasks: Batch Print SF Waybills

## Prerequisites
- [ ] Obtain Kuaimai cloud printing account credentials (appId, appSecret)
- [ ] Configure test printer in Kuaimai platform
- [ ] Verify SF Express API access for waybill printing

## Phase 1: Backend Foundation (Days 1-3)

### 1.1 PDF Conversion Service
- [ ] Add pdf2image to requirements.txt
- [ ] Create `app/services/shipping/pdf_conversion_service.py`
- [ ] Implement `convert_pdf_to_images()` method with pdf2image
- [ ] Implement `optimize_for_thermal_printer()` with Pillow
- [ ] Implement `image_to_base64()` encoding method
- [ ] Add error handling for corrupted PDFs
- [ ] Write unit tests for PDF conversion
- [ ] Test with sample SF waybill PDFs

### 1.2 Kuaimai Cloud Printing Service
- [ ] Create `app/services/printing/` directory
- [ ] Create `app/services/printing/kuaimai_service.py`
- [ ] Implement `_generate_sign()` for MD5 signature
- [ ] Implement `print_image()` for tsplXmlWrite API
- [ ] Implement `list_printers()` with 5-minute cache
- [ ] Implement `get_print_status()` for job tracking
- [ ] Add environment variable validation
- [ ] Add retry logic for rate limiting
- [ ] Write unit tests for signature generation
- [ ] Write integration tests with mock API

### 1.3 SF Express Waybill API Integration
- [ ] Add `get_waybill_pdf()` method to `SFExpressService`
- [ ] Implement API call to `COM_RECE_CLOUD_PRINT_WAYBILLS`
- [ ] Handle binary PDF response
- [ ] Add retry logic for transient failures
- [ ] Validate rental has tracking number before API call
- [ ] Write unit tests for API integration
- [ ] Test with SF Express sandbox environment

## Phase 2: Orchestration Layer (Days 4-5)

### 2.1 Waybill Print Service
- [ ] Create `app/services/shipping/waybill_print_service.py`
- [ ] Implement `WaybillPrintService` class
- [ ] Implement `print_single_waybill()` method
  - [ ] Get PDF from SF Express
  - [ ] Convert PDF to images
  - [ ] Send images to Kuaimai printer
  - [ ] Return detailed result
- [ ] Implement `batch_print_waybills()` method
  - [ ] Filter valid rentals
  - [ ] Process in parallel (ThreadPoolExecutor)
  - [ ] Aggregate results
  - [ ] Handle partial failures
- [ ] Add comprehensive error handling
- [ ] Add logging for audit trail
- [ ] Write unit tests
- [ ] Write integration tests

### 2.2 API Routes
- [ ] Add routes to `app/routes/shipping_batch_api.py`
- [ ] Implement `POST /api/shipping-batch/print-waybills`
  - [ ] Validate request parameters
  - [ ] Call `WaybillPrintService.batch_print_waybills()`
  - [ ] Return standardized response
- [ ] Implement `GET /api/shipping-batch/printers`
  - [ ] Call `KuaimaiPrintService.list_printers()`
  - [ ] Handle errors gracefully
- [ ] Add request validation
- [ ] Add rate limiting (100 waybills per request)
- [ ] Write API tests

## Phase 3: Frontend UI (Days 6-7)

### 3.1 Batch Shipping View Enhancement
- [ ] Add state variables to `BatchShippingView.vue`
  - [ ] `printers: Ref<Printer[]>`
  - [ ] `selectedPrinter: Ref<string>`
  - [ ] `waybillPrintDialogVisible: Ref<boolean>`
  - [ ] `printing: Ref<boolean>`
  - [ ] `printProgress: Ref<number>`
  - [ ] `printResults: Ref<PrintResults>`
- [ ] Add "批量打印快递面单" button to action bar
- [ ] Implement `waybillCount` computed property
  - [ ] Count rentals with tracking numbers
  - [ ] Exclude already shipped rentals
- [ ] Create printer selection dialog component
  - [ ] Printer dropdown
  - [ ] Waybill count display
  - [ ] Confirm/cancel buttons
- [ ] Implement `fetchPrinters()` method
- [ ] Implement `showWaybillPrintDialog()` method
- [ ] Implement `confirmPrintWaybills()` method
  - [ ] Call batch print API
  - [ ] Update progress bar
  - [ ] Handle results
- [ ] Add error handling and user feedback
- [ ] Style dialog components

### 3.2 Results Display
- [ ] Create results summary component
  - [ ] Success/failure count
  - [ ] Success alert for all success
  - [ ] Warning alert for partial failure
- [ ] Create failed items list component
  - [ ] Rental ID
  - [ ] Error message
  - [ ] Retry button (future)
- [ ] Implement progress bar
- [ ] Add auto-close logic (2 seconds after all success)
- [ ] Add manual close for failures

### 3.3 Printer Selection Persistence
- [ ] Save selected printer to localStorage
- [ ] Load last selected printer on dialog open
- [ ] Clear saved selection if printer no longer exists

## Phase 4: Testing & Validation (Days 8-9)

### 4.1 Unit Testing
- [ ] Test PDF conversion with various formats
- [ ] Test Kuaimai signature generation
- [ ] Test SF API error handling
- [ ] Test batch processing logic
- [ ] Achieve >80% code coverage

### 4.2 Integration Testing
- [ ] Test end-to-end flow with test printer
- [ ] Test with real SF waybill PDFs
- [ ] Test partial failure scenarios
- [ ] Test network error handling
- [ ] Test concurrent printing requests

### 4.3 Manual Testing
- [ ] Print single waybill
- [ ] Print batch of 5 waybills
- [ ] Print batch of 20 waybills
- [ ] Test with printer offline
- [ ] Test with invalid printer ID
- [ ] Test SF API errors
- [ ] Verify print quality on physical printer
- [ ] Test on different browsers
- [ ] Test on mobile devices

### 4.4 Performance Testing
- [ ] Measure single waybill print time
- [ ] Measure batch print time (10, 20, 50 waybills)
- [ ] Monitor memory usage during batch print
- [ ] Verify no memory leaks

## Phase 5: Documentation & Deployment (Day 10)

### 5.1 Documentation
- [ ] Update README with Kuaimai setup instructions
- [ ] Document environment variables
- [ ] Add API documentation for new endpoints
- [ ] Create troubleshooting guide
- [ ] Document printer configuration steps

### 5.2 Configuration
- [ ] Add environment variables to .env.example
  - [ ] `KUAIMAI_APP_ID`
  - [ ] `KUAIMAI_APP_SECRET`
  - [ ] `KUAIMAI_DEFAULT_PRINTER_ID` (optional)
- [ ] Update Docker configuration if needed
- [ ] Create production deployment checklist

### 5.3 Deployment
- [ ] Deploy to staging environment
- [ ] Perform smoke tests
- [ ] Deploy to production
- [ ] Monitor error logs for 24 hours
- [ ] Collect user feedback

## Dependencies
- Phase 2 depends on Phase 1 completion
- Phase 3 depends on Phase 2 API routes
- Phase 4 can run in parallel with Phase 3
- Phase 5 depends on all previous phases

## Estimated Timeline
- **Phase 1**: 3 days (Backend foundation)
- **Phase 2**: 2 days (Orchestration)
- **Phase 3**: 2 days (Frontend)
- **Phase 4**: 2 days (Testing)
- **Phase 5**: 1 day (Documentation & deployment)
- **Total**: 10 working days

## Risk Mitigation
- **Risk**: SF API rate limiting
  - **Mitigation**: Implement request queuing and backoff
- **Risk**: PDF conversion failures
  - **Mitigation**: Graceful degradation, detailed error messages
- **Risk**: Printer connectivity issues
  - **Mitigation**: Timeout handling, status checking
- **Risk**: Large batch operations timeout
  - **Mitigation**: Process in chunks, async processing

## Success Metrics
- [ ] Successfully print 50 consecutive waybills without errors
- [ ] Average print time <5 seconds per waybill
- [ ] User satisfaction: positive feedback from 3+ users
- [ ] Zero critical bugs in first week of production
