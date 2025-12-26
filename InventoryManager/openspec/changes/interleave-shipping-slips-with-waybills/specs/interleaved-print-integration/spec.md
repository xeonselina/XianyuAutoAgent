# Capability: Interleaved Print Integration

## Summary
Enable interleaving of simplified shipping slips with waybill printing in batch operations, allowing face-up matching for packing efficiency.

## ADDED Requirements

### Requirement: Batch print interleaving
The system SHALL print a simplified shipping slip immediately after each waybill in an alternating pattern during batch operations.

#### Scenario: Single order batch print
**GIVEN** 1 rental order (ID: 123) ready for shipping
**WHEN** user clicks "批量打印面单"
**THEN** system prints waybill for rental #123
**AND** immediately prints shipping slip for rental #123
**AND** both documents are sent to the same Kuaimai printer
**AND** user sees confirmation: "已打印 1 个订单的面单和发货单"

#### Scenario: Multiple orders batch print
**GIVEN** 5 rental orders (IDs: 101, 102, 103, 104, 105) ready for shipping
**WHEN** user clicks "批量打印面单"
**THEN** system prints in exact order: Waybill₁ → Slip₁ → Waybill₂ → Slip₂ → Waybill₃ → Slip₃ → Waybill₄ → Slip₄ → Waybill₅ → Slip₅
**AND** progress shows "正在打印第 3/5 单..." during execution
**AND** user sees final summary: "成功: 5/5 订单"

#### Scenario: Mixed success in batch
**GIVEN** 3 rental orders where rental #102 waybill print fails
**WHEN** user batch prints
**THEN** rental #101 has both waybill and slip printed successfully
**AND** rental #102 waybill fails and slip is skipped
**AND** rental #103 has both waybill and slip printed successfully
**AND** final summary shows: "成功: 2/3 订单, 面单: 2/3 成功, 发货单: 2/3 成功"
**AND** failure details include rental #102 error message

### Requirement: Simplified shipping slip format
The system SHALL generate shipping slips formatted for 80mm thermal paper with only essential information.

#### Scenario: Basic shipping slip content
**GIVEN** rental order with customer "张三", phone "13812345678", address "广东省广州市天河区车陂路123号", device "Sony A7M4" with SN "ABC123456"
**WHEN** shipping slip is generated
**THEN** slip displays scannable barcode encoding "RNT-{rental_id}"
**AND** displays "订单号: RNT-{rental_id}"
**AND** displays "收货人: 张三"
**AND** displays "电话: 138****5678" (masked)
**AND** displays "地址: 广东省广州市天河区车陂路123号"
**AND** displays "设备: Sony A7M4"
**AND** displays "序列号: ABC123456"
**AND** displays rental period and return deadline
**AND** barcode is scannable with standard barcode reader

#### Scenario: Long address wrapping
**GIVEN** rental with address "广东省深圳市南山区科技园南区深圳湾科技生态园10栋A座2008室某某科技有限公司收"
**WHEN** shipping slip is generated
**THEN** address text wraps to multiple lines without truncation
**AND** total slip height remains under 200mm
**AND** all text is readable on thermal print

#### Scenario: Null destination handling
**GIVEN** rental where destination field is null
**WHEN** shipping slip is generated
**THEN** slip displays "地址: 未知"
**AND** generation does not fail

### Requirement: Shipping slip image generation
The system SHALL convert the SimplifiedShippingSlip Vue component into a base64-encoded PNG image suitable for thermal printing.

#### Scenario: Successful image generation
**GIVEN** rental ID 123 with complete data exists in database
**WHEN** ShippingSlipImageService.generate_slip_image(123) is called
**THEN** service retrieves rental data
**AND** renders SimplifiedShippingSlip component with Puppeteer
**AND** captures screenshot as PNG at 203 DPI
**AND** encodes PNG to base64
**AND** returns base64 string within 2 seconds
**AND** image width is 640px (80mm @ 203 DPI)

#### Scenario: Missing rental data
**GIVEN** rental ID 999 does not exist in database
**WHEN** ShippingSlipImageService.generate_slip_image(999) is called
**THEN** service raises SlipGenerationError with message "租赁记录不存在: ID 999"
**AND** error is logged with severity ERROR

#### Scenario: Puppeteer timeout
**GIVEN** Puppeteer rendering takes more than 5 seconds
**WHEN** ShippingSlipImageService.generate_slip_image(123) is called
**THEN** service raises SlipGenerationError with message containing "渲染超时"
**AND** browser page is forcefully closed to prevent memory leak

### Requirement: Kuaimai printer integration for slips
The system SHALL send shipping slip images to Kuaimai cloud printer using the same API as waybill printing.

#### Scenario: Successful print submission
**GIVEN** shipping slip image as base64 string
**WHEN** KuaimaiPrintService.print_image(image_base64, copies=1) is called
**THEN** service sends image to Kuaimai API
**AND** receives job_id within 3 seconds
**AND** returns success response: {"success": true, "job_id": "KM_20250110_123456"}

#### Scenario: Printer offline
**GIVEN** Kuaimai printer is offline
**WHEN** KuaimaiPrintService.print_image(...) is called
**THEN** service receives API error "打印机离线"
**AND** service does NOT retry (offline is not transient)
**AND** service returns error response: {"success": false, "error": "打印机离线,请检查设备状态"}

#### Scenario: API rate limiting
**GIVEN** Kuaimai API returns 429 (Too Many Requests)
**WHEN** KuaimaiPrintService.print_image(...) is called
**THEN** service waits 2 seconds
**AND** retries the request (up to 3 attempts total)
**AND** returns success if retry succeeds
**AND** returns error if all 3 attempts fail

### Requirement: Error handling and partial success
The system SHALL continue processing remaining orders when individual shipping slips fail and report success/failure details.

#### Scenario: Slip generation failure mid-batch
**GIVEN** 5 rental orders where rental #3 slip generation crashes
**WHEN** user batch prints
**THEN** rentals #1-2 print both waybill and slip successfully
**AND** rental #3 prints waybill successfully but slip fails
**AND** rentals #4-5 print both waybill and slip successfully
**AND** error is logged for rental #3
**AND** final summary shows successful and failed counts

#### Scenario: Complete failure due to printer offline
**GIVEN** 5 rental orders and Kuaimai printer is offline
**WHEN** user batch prints
**THEN** all 10 print jobs (5 waybills + 5 slips) fail
**AND** error message shows "打印机离线,请检查设备后重试"
**AND** user can retry after fixing printer

### Requirement: User control for shipping slips
The system SHALL provide a checkbox in the batch print dialog to enable or disable shipping slip printing.

#### Scenario: Disable shipping slips
**GIVEN** user is in batch print dialog
**WHEN** user unchecks "同时打印发货单"
**AND** clicks "确认打印"
**THEN** system prints only waybills (no shipping slips)
**AND** print sequence is: Waybill₁ → Waybill₂ → ... → WaybillN
**AND** progress shows "正在打印面单 3/10..."

#### Scenario: Enable shipping slips by default
**GIVEN** user opens batch print dialog
**THEN** "同时打印发货单" checkbox is checked by default
**WHEN** user clicks "确认打印" without changing checkbox
**THEN** system prints both waybills and slips in alternating sequence

### Requirement: Performance constraints
Batch printing with shipping slips SHALL complete within reasonable time limits.

#### Scenario: 10-order batch performance
**GIVEN** 10 rental orders ready for shipping
**WHEN** user initiates batch print at time T₀
**THEN** first waybill starts printing by T₀ + 2s
**AND** all 20 print jobs (10 waybills + 10 slips) complete by T₀ + 30s
**AND** average time per order is ≤ 3 seconds
**AND** memory usage increases by less than 500MB
**AND** no browser crash or timeout errors occur
