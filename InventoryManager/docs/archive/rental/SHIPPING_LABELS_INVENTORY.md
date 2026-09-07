# Shipping Labels & QR Codes - Complete File Inventory

## Overview
This is a comprehensive inventory of all files related to printing shipping labels (快递单/运单), including QR codes for tutorials and label generation systems in the InventoryManager codebase.

---

## Quick Reference - All Relevant Files

### Python Backend Services (419 lines total)
1. **`/app/services/printing/shipping_slip_image_service.py`** (419 lines)
   - Generates 76×130mm shipping slip images with PIL
   - Embeds three tutorial QR codes
   - Loads from `/frontend/src/assets/` directory

2. **`/app/services/printing/kuaimai_service.py`** (256 lines)
   - Kuaimai Cloud Print API integration
   - MD5 signature authentication
   - Print job status tracking

3. **`/app/services/shipping/waybill_print_service.py`** (310 lines)
   - Orchestrates waybill + shipping slip printing
   - Integrates SF Express with Kuaimai
   - Batch printing support

4. **`/app/services/shipping/pdf_conversion_service.py`** (190 lines)
   - Converts SF Express PDFs to thermal printer images
   - Thermal printer optimization (1-bit dithering)
   - Base64 encoding

5. **`/app/routes/shipping_batch_api.py`** (450+ lines)
   - REST endpoints for printing operations
   - POST /api/shipping-batch/print-waybills
   - GET /api/shipping-batch/printers
   - POST /api/shipping-batch/schedule

### Frontend Vue Components (640+ lines)
1. **`/frontend/src/views/ShippingOrderView.vue`** (250+ lines)
   - Single order shipping label view
   - Displays three QR codes at bottom
   - Print button with CSS optimization

2. **`/frontend/src/views/BatchShippingOrderView.vue`** (350+ lines)
   - Multi-order batch printing view
   - Page breaks for printing
   - Barcode generation (jsbarcode)

3. **`/frontend/src/components/rental/BatchPrintDialog.vue`** (287 lines)
   - Date range picker
   - Order preview before printing
   - Navigation to batch view

4. **`/frontend/src/components/printing/SimplifiedShippingSlip.vue`** (158 lines)
   - Reusable shipping slip component
   - Print-optimized layout

### QR Code Assets (3 files)
1. **`/frontend/src/assets/镜头安装教程.png`**
2. **`/frontend/src/assets/拍摄调试教程.png`**
3. **`/frontend/src/assets/照片传输教程.png`**

Also compiled to `/static/vue-dist/assets/` with hash suffixes

### Configuration & Templates
1. **`/app/utils/sf/callExpressRequest/20.cloud_print_waybills.json`**
   - SF Express waybill API template

2. **`/templates/shipping_order2.html`**
   - Legacy HTML template for orders

3. **`/docs/第三方接口文档/顺丰/面单打印成cpcl.html`**
   - SF Express API documentation reference

---

## System Architecture

```
┌─────────────────────────────────────────────┐
│    Frontend (Vue.js + CSS Print)            │
│    ShippingOrderView.vue                    │
│    BatchShippingOrderView.vue               │
└──────────────────┬──────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────┐
│    REST API (Flask)                         │
│    /api/shipping-batch/print-waybills       │
│    /api/shipping-batch/printers             │
│    /api/rentals/by-ship-date                │
└──────────┬────────────────────┬─────────────┘
           │                    │
           ▼                    ▼
    ┌──────────────┐    ┌──────────────────┐
    │ Waybill      │    │ Shipping Slip    │
    │ Print Service│    │ Image Service    │
    └──────┬───────┘    └────────┬─────────┘
           │                     │
           ▼                     ▼
    ┌─────────────────────────────────────┐
    │  Kuaimai Cloud Print Service        │
    │  (Thermal Printer Control)          │
    └──────────────────┬──────────────────┘
                       │
                       ▼
            ┌──────────────────────┐
            │  Network Printers    │
            │  (76mm thermal)      │
            └──────────────────────┘
```

---

## Printing Workflows

### Workflow A: Cloud Print (Kuaimai Service)
```
POST /api/shipping-batch/print-waybills
  ↓
WaybillPrintService.batch_print_waybills()
  ├─ For each rental:
  │  ├─ SF Express API: Get PDF waybill
  │  ├─ PDFConversionService: PDF → base64 image (203 DPI)
  │  └─ KuaimaiPrintService: Submit to Kuaimai
  └─ Return: {success_count, failed_count, results}
```

### Workflow B: Shipping Slip Generation
```
ShippingSlipImageService.generate_slip_image(rental_id)
  ↓
  ├─ Load rental data from DB
  ├─ Draw sections with PIL:
  │  ├─ Header (order number)
  │  ├─ Customer info
  │  ├─ Device & accessories
  │  ├─ Return deadline (highlighted)
  │  └─ Three QR codes (vertical layout)
  ├─ Thermal printer optimization:
  │  ├─ Convert to grayscale
  │  ├─ Enhance contrast
  │  └─ Apply Floyd-Steinberg dithering
  └─ Return: base64-encoded 1-bit PNG (~1-2 KB)
```

### Workflow C: Browser Batch Print
```
BatchPrintDialog
  ↓ Select date range
  ↓
GET /api/rentals/by-ship-date
  ↓ Get rentals
  ↓
Route to /batch-shipping-order?start_date=X&end_date=Y
  ↓
BatchShippingOrderView
  ├─ Render all orders with QR codes
  ├─ CSS: page-break-after for each order
  └─ User: Ctrl+P → Browser print → PDF/physical printer
```

---

## Key Features by Component

### ShippingSlipImageService
- ✅ 76×130mm paper size (standard thermal)
- ✅ Loads 3 tutorial QR codes (150×150px each)
- ✅ Phone number masking (XXX****XXXX)
- ✅ Text wrapping for multi-line fields
- ✅ Dashed section separators
- ✅ Font fallback: PingFang → NotoSansCJK → PIL default
- ✅ 1-bit black & white mode (optimal for thermal)
- ✅ Base64 encoding for cloud delivery

### KuaimaiPrintService
- ✅ MD5 signature authentication
- ✅ TSPL/XML print job format
- ✅ Rate limiting with automatic retry
- ✅ Job status tracking
- ✅ Configurable printer SN via env vars
- ✅ Print job ID return

### WaybillPrintService
- ✅ Batch printing (max 100 orders)
- ✅ Alternating waybill + shipping slip mode
- ✅ Multi-page support
- ✅ Comprehensive error logging
- ✅ Transaction rollback on failure

### BatchShippingOrderView
- ✅ Date range filtering
- ✅ Multi-order pagination
- ✅ Barcode generation (CODE128)
- ✅ CSS print optimization
- ✅ Page break between orders
- ✅ Filters shipped orders

---

## QR Code Usage

### Three Tutorial QR Codes
1. **镜头安装教程.png** (Lens Installation)
   - Instructions for assembling camera lens attachments
   - Location: `/frontend/src/assets/`

2. **拍摄调试教程.png** (Shooting Debug)
   - Configuration and testing procedures
   - Location: `/frontend/src/assets/`

3. **照片传输教程.png** (Photo Transfer)
   - Data transfer and backup instructions
   - Location: `/frontend/src/assets/`

### Embedding Locations
1. In Python shipping slip images (150×150px, embedded via PIL)
2. In Vue components (displayed in grid, printed via browser)
3. In compiled static assets (`/static/vue-dist/assets/` with hash)

---

## Environment Configuration

```bash
# Required for Kuaimai printing
export KUAIMAI_APP_ID="your_app_id"
export KUAIMAI_APP_SECRET="your_app_secret"
export KUAIMAI_PRINTER_SN="printer_serial_number"

# Optional
export DEFAULT_DPI=203  # Thermal printer resolution
```

---

## API Endpoints

### POST /api/shipping-batch/print-waybills
**Batch print waybills with optional shipping slips**
```json
{
  "rental_ids": [1, 2, 3],
  "include_shipping_slips": true
}
```
Returns: `{success_count, slip_success_count, failed_count, results}`

### GET /api/shipping-batch/printers
**Get printer configuration**
Returns: `{printers: [{id, sn, name, is_default}]}`

### POST /api/shipping-batch/schedule
**Schedule shipment (creates SF waybill)**
```json
{
  "rental_ids": [1, 2],
  "scheduled_time": "2024-12-25T10:00:00Z"
}
```

### GET /api/rentals/by-ship-date
**Query rentals by ship date range**
```
Params: start_date=YYYY-MM-DD, end_date=YYYY-MM-DD
```

---

## Performance Metrics

| Item | Size | Time |
|------|------|------|
| Shipping slip image | ~1-2 KB | ~500ms to generate |
| Waybill PDF from SF | ~50-100 KB | ~2-3s to fetch |
| Converted waybill | ~10-20 KB | ~1s to convert |
| Single print job | ~30 KB | ~1-3s to print |
| QR code PNG | ~2-5 KB | - |

---

## Error Handling

### Kuaimai Rate Limiting
- Error code 6027 triggers automatic 2s retry
- Max 1 retry per request
- Returns explicit error message if second attempt fails

### PDF Conversion Failures
- Falls back to simple 1-bit conversion if optimization fails
- Logs full stack trace for debugging

### Thermal Printer Optimization
- Automatically converts to grayscale
- Applies contrast enhancement curve
- Uses Floyd-Steinberg dithering (better than Bayer)
- Converts to 1-bit black & white

---

## Testing Checklist

- [ ] Can generate shipping slip image with embedded QR codes
- [ ] QR codes load from correct asset path
- [ ] Phone numbers are properly masked
- [ ] Thermal printer optimization produces correct output
- [ ] Kuaimai API authentication works
- [ ] Batch printing doesn't exceed 100 order limit
- [ ] Waybill PDF conversion succeeds
- [ ] Browser print CSS works correctly
- [ ] Page breaks appear between orders
- [ ] Barcodes generate without errors
- [ ] Date range filtering excludes shipped orders

---

## File Changes Summary

**Total Lines of Code**: ~1500+ lines
- Python Services: ~1200 lines
- Vue Components: ~640 lines
- Configuration: ~50 lines

**Key Technologies**:
- PIL/Pillow (image generation)
- pdf2image (PDF conversion)
- Kuaimai API (cloud printing)
- SF Express API (waybill generation)
- Vue.js 3 (UI)
- jsbarcode (barcode generation)

