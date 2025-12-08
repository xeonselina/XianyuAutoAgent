# Shipping Order Scan Capability

## ADDED Requirements

### Requirement: QR Code on Shipping Order

The system SHALL display a QR code on each shipping order document containing the rental ID for scanner identification.

#### Scenario: Generate QR code

- **WHEN** system renders shipping order template
- **THEN** a QR code is generated containing the rental ID (e.g., "123")
- **AND** QR code is positioned in top-right corner
- **AND** QR code size is 80x80 pixels
- **AND** QR code is visible in both screen view and print preview

#### Scenario: Scan QR code with scanner gun

- **WHEN** user scans shipping order QR code with barcode scanner
- **THEN** scanner outputs the rental ID digits
- **AND** rental ID is captured by browser keyboard event listener

### Requirement: Rental QR Code Scanning

The system SHALL detect rental QR code scans and display rental details for verification.

#### Scenario: Scan rental QR code

- **WHEN** user scans rental QR code in batch shipping page
- **AND** scanner inputs rental ID followed by Enter key
- **THEN** system calls `POST /api/shipping-batch/scan-rental` with rental_id
- **AND** displays dialog with rental details (customer, phone, address, device, accessories, dates)
- **AND** auto-focuses the dialog to prevent background interactions

#### Scenario: Invalid rental ID

- **WHEN** scanned rental ID does not exist in database
- **THEN** system displays error toast "租赁记录不存在 (ID: {id})"
- **AND** does not open rental details dialog

#### Scenario: Scan timeout detection

- **WHEN** scanner inputs characters with < 50ms interval
- **AND** followed by 200ms pause
- **THEN** system treats accumulated input as one complete scan
- **AND** processes the scanned value

### Requirement: Waybill Number Scanning

The system SHALL accept SF Express waybill scans and record them to rental records.

#### Scenario: Scan waybill after rental

- **WHEN** rental details dialog is open
- **AND** user scans SF Express waybill barcode
- **THEN** system calls `POST /api/shipping-batch/record-waybill` with rental_id and waybill_no
- **AND** updates rental's `sf_waybill_no` field
- **AND** closes the dialog
- **AND** updates order status in table to "已录入运单"

#### Scenario: Invalid waybill format

- **WHEN** scanned waybill does not match pattern (alphanumeric, 10+ chars)
- **THEN** system displays error toast "运单号格式无效: {waybill}"
- **AND** keeps dialog open for retry

#### Scenario: Duplicate waybill scan

- **WHEN** scanned waybill already exists in another rental
- **THEN** system displays warning "运单号已被使用 (Rental: {existing_id})"
- **AND** asks user to confirm override or cancel

### Requirement: Voice Prompt

The system SHALL provide voice prompts to guide the scanning process.

#### Scenario: Voice prompt after rental scan

- **WHEN** rental QR code is successfully scanned
- **AND** rental details dialog opens
- **THEN** system plays voice "请扫描顺丰面单"
- **AND** voice is in Chinese (zh-CN)
- **AND** voice rate is 1.0 (normal speed)

#### Scenario: Voice prompt after waybill scan

- **WHEN** waybill is successfully recorded
- **THEN** system plays voice "已录入"

#### Scenario: Voice prompt disabled

- **WHEN** user has disabled voice prompts in settings
- **OR** browser does not support Web Speech API
- **THEN** system skips voice playback
- **AND** relies on visual feedback only

### Requirement: Barcode Scanner Input Detection

The system SHALL distinguish between rental QR codes and SF waybill barcodes based on input patterns.

#### Scenario: Detect rental ID pattern

- **WHEN** scanned input matches pattern `^\d+$` (pure digits)
- **THEN** system treats it as rental ID
- **AND** triggers rental scan handler

#### Scenario: Detect waybill pattern

- **WHEN** scanned input matches pattern `^[A-Z0-9]{10,}$` (alphanumeric, 10+ chars)
- **THEN** system treats it as SF Express waybill
- **AND** triggers waybill scan handler

#### Scenario: Unrecognized scan pattern

- **WHEN** scanned input does not match known patterns
- **THEN** system displays warning "无法识别的扫码内容: {input}"
- **AND** ignores the scan
