# batch-print-ui Specification

## Purpose
TBD - created by archiving change batch-print-sf-waybills. Update Purpose after archive.
## Requirements
### Requirement: Display batch print waybill button
The system SHALL show "批量打印快递面单" button in batch shipping management interface.

#### Scenario: Show button when rentals have tracking numbers
**GIVEN** user is on batch shipping page
**AND** 3 rentals have tracking numbers
**WHEN** page loads
**THEN** "批量打印快递面单" button is visible
**AND** button shows count "(3)" next to label
**AND** button is enabled

#### Scenario: Disable button when no tracking numbers
**GIVEN** user is on batch shipping page
**AND** no rentals have tracking numbers
**WHEN** page loads
**THEN** "批量打印快递面单" button is visible
**AND** button shows count "(0)"
**AND** button is disabled

#### Scenario: Exclude already shipped rentals from count
**GIVEN** 5 rentals with tracking numbers
**AND** 2 rentals have status "shipped"
**WHEN** calculating waybill count
**THEN** button shows count "(3)"
**AND** only not-shipped rentals are counted

### Requirement: Show printer selection dialog
The system SHALL display dialog for selecting printer before printing.

#### Scenario: Open printer selection dialog
**GIVEN** user clicks "批量打印快递面单" button
**WHEN** dialog opens
**THEN** dialog shows count of waybills to print
**AND** dialog includes printer dropdown selector
**AND** dialog shows confirm and cancel buttons

#### Scenario: Load available printers
**GIVEN** printer selection dialog is opening
**WHEN** dialog is displayed
**THEN** the system fetches list of available printers
**AND** populates dropdown with printer names
**AND** shows loading indicator while fetching

#### Scenario: Handle no printers available
**GIVEN** Kuaimai account has no printers configured
**WHEN** fetching printer list
**THEN** dialog shows "无可用打印机" message
**AND** confirm button is disabled
**AND** provides link to printer setup instructions

### Requirement: Execute batch printing operation
The system SHALL submit print jobs for all selected rentals.

#### Scenario: Print waybills with selected printer
**GIVEN** user selected printer "KM-118" from dropdown
**AND** 5 rentals are ready to print
**WHEN** user clicks confirm button
**THEN** the system sends POST request to /api/shipping-batch/print-waybills
**AND** request includes rental_ids array
**AND** request includes printer_id
**AND** loading indicator is shown

#### Scenario: Show printing progress
**GIVEN** printing operation is in progress
**WHEN** API is processing
**THEN** dialog shows progress bar
**AND** button label changes to "打印中..."
**AND** button is disabled
**AND** cancel button is disabled

### Requirement: Display printing results
The system SHALL show summary of print job outcomes.

#### Scenario: All waybills printed successfully
**GIVEN** 5 waybills were submitted for printing
**AND** all print jobs succeeded
**WHEN** printing completes
**THEN** dialog shows success alert
**AND** message displays "成功: 5 / 失败: 0"
**AND** success toast notification appears
**AND** progress bar shows 100% in green

#### Scenario: Some waybills failed to print
**GIVEN** 5 waybills were submitted
**AND** 2 print jobs failed
**WHEN** printing completes
**THEN** dialog shows warning alert
**AND** message displays "成功: 3 / 失败: 2"
**AND** failed items list is shown
**AND** each failed item shows rental ID and error message

#### Scenario: Display detailed failure reasons
**GIVEN** rental ID 123 failed with "打印机离线"
**AND** rental ID 456 failed with "PDF转换失败"
**WHEN** results are displayed
**THEN** failed items section shows:
```
订单 123: 打印机离线
订单 456: PDF转换失败
```

### Requirement: Handle printing errors gracefully
The system SHALL provide clear error messages for printing failures.

#### Scenario: Handle network error
**GIVEN** printing API request fails with network error
**WHEN** error occurs
**THEN** error toast displays "网络错误，请稍后重试"
**AND** dialog remains open
**AND** user can retry operation

#### Scenario: Handle server error
**GIVEN** API returns 500 server error
**WHEN** error occurs
**THEN** error toast displays "服务器错误"
**AND** detailed error is logged to console
**AND** dialog shows error state

### Requirement: Provide retry mechanism
The system SHALL allow users to retry failed print jobs.

#### Scenario: Retry all failed jobs
**GIVEN** 2 out of 5 print jobs failed
**AND** results are displayed
**WHEN** user clicks "重试失败项" button
**THEN** the system resubmits only failed rental IDs
**AND** shows progress for retry operation
**AND** updates results with retry outcome

### Requirement: Close dialog after successful completion
The system SHALL auto-close dialog when all prints succeed.

#### Scenario: Auto-close after all success
**GIVEN** all print jobs succeeded
**WHEN** results are displayed for 2 seconds
**THEN** dialog automatically closes
**AND** user returns to batch shipping list
**AND** success message remains visible briefly

#### Scenario: Keep dialog open on failures
**GIVEN** some print jobs failed
**WHEN** results are displayed
**THEN** dialog remains open
**AND** user must manually close dialog
**AND** can review failure details

### Requirement: Disable button during printing
The system SHALL prevent concurrent print operations.

#### Scenario: Prevent double-click during printing
**GIVEN** printing operation is in progress
**WHEN** user attempts to click print button again
**THEN** button is disabled
**AND** no duplicate request is sent
**AND** existing operation continues

### Requirement: Persist printer selection
The system SHALL remember user's last selected printer.

#### Scenario: Save printer selection
**GIVEN** user selected printer "KM-118"
**AND** successfully printed waybills
**WHEN** user opens print dialog again
**THEN** dropdown preselects "KM-118"
**AND** selection is stored in localStorage

#### Scenario: Clear selection if printer no longer available
**GIVEN** last selected printer "OLD-PRINTER" was removed
**WHEN** fetching printer list
**THEN** the system detects printer not in list
**AND** clears saved selection
**AND** dropdown shows no selection

