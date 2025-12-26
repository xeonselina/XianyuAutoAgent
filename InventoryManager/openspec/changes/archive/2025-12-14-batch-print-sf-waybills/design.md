# Design: Batch Print SF Waybills

## Architecture Overview

```
┌─────────────────────┐
│  BatchShippingView  │
│   (Frontend/Vue)    │
└──────────┬──────────┘
           │
           │ POST /api/shipping-batch/print-waybills
           │ { rental_ids: [...], printer_id: "..." }
           ▼
┌─────────────────────────────────────┐
│  ShippingBatchAPI                   │
│  (Flask Route)                      │
└──────────┬──────────────────────────┘
           │
           │ Call batch_print_waybills()
           ▼
┌─────────────────────────────────────┐
│  WaybillPrintService                │
│  (New Service Layer)                │
└───┬─────────┬───────────┬───────────┘
    │         │           │
    │         │           │ Convert PDF → Image
    │         │           ▼
    │         │     ┌──────────────────┐
    │         │     │ PDFConversion    │
    │         │     │ Service          │
    │         │     └──────────────────┘
    │         │           │
    │         │           │ pdf2image + Pillow
    │         │           ▼
    │         │     [Base64 Images]
    │         │
    │         │ Get waybill PDF
    │         ▼
    │   ┌─────────────────────┐
    │   │ SFExpressService    │
    │   │ (Existing)          │
    │   └───────┬─────────────┘
    │           │
    │           │ API: COM_RECE_CLOUD_PRINT_WAYBILLS
    │           ▼
    │     [SF Express Platform]
    │
    │ Send to printer
    ▼
┌─────────────────────┐
│ KuaimaiPrint        │
│ Service (New)       │
└───────┬─────────────┘
        │
        │ API: tsplXmlWrite
        ▼
  [Kuaimai Cloud Print]
        │
        ▼
  [Physical Printer]
```

## Component Design

### 1. Backend Services

#### WaybillPrintService
**Location**: `app/services/shipping/waybill_print_service.py`

**Responsibilities**:
- Orchestrate the entire printing workflow
- Batch processing with error handling
- Return detailed results for each rental

**Key Methods**:
```python
class WaybillPrintService:
    def __init__(self):
        self.sf_service = get_sf_express_service()
        self.kuaimai_service = KuaimaiPrintService()
        self.pdf_converter = PDFConversionService()

    def batch_print_waybills(
        self,
        rental_ids: List[int],
        printer_id: str
    ) -> Dict:
        """
        Print waybills for multiple rentals
        Returns: {
            'total': int,
            'success': int,
            'failed': int,
            'results': [
                {
                    'rental_id': int,
                    'success': bool,
                    'message': str,
                    'job_id': str (optional)
                }
            ]
        }
        """

    def print_single_waybill(
        self,
        rental: Rental,
        printer_id: str
    ) -> Dict:
        """Print waybill for single rental"""
```

#### SFExpressService (Enhancement)
**Location**: `app/services/shipping/sf_express_service.py`

**New Method**:
```python
def get_waybill_pdf(self, rental) -> Dict:
    """
    Get waybill PDF from SF Express

    API: COM_RECE_CLOUD_PRINT_WAYBILLS

    Returns: {
        'success': bool,
        'pdf_data': bytes,  # Raw PDF bytes
        'message': str
    }
    """
```

**Implementation Notes**:
- Use existing `_call_sf_express_service` method
- Service code: `COM_RECE_CLOUD_PRINT_WAYBILLS`
- Include rental details and tracking number
- Handle binary PDF response

#### PDFConversionService
**Location**: `app/services/shipping/pdf_conversion_service.py`

**Responsibilities**:
- Convert PDF to images
- Optimize images for thermal printing
- Encode images as base64

**Key Methods**:
```python
class PDFConversionService:
    def convert_pdf_to_images(
        self,
        pdf_data: bytes,
        dpi: int = 203
    ) -> List[bytes]:
        """
        Convert PDF to list of PNG images

        Args:
            pdf_data: Raw PDF bytes
            dpi: Printer resolution (203 or 300)

        Returns: List of PNG image bytes
        """

    def image_to_base64(self, image_data: bytes) -> str:
        """Encode image as base64 string"""

    def optimize_for_thermal_printer(
        self,
        image: PIL.Image
    ) -> PIL.Image:
        """
        Optimize image for thermal printing
        - Convert to 1-bit black/white
        - Adjust contrast
        - Resize if needed
        """
```

#### KuaimaiPrintService
**Location**: `app/services/printing/kuaimai_service.py`

**Responsibilities**:
- Interact with Kuaimai cloud printing API
- Handle authentication and signing
- Submit print jobs
- Track printing status

**Key Methods**:
```python
class KuaimaiPrintService:
    def __init__(self):
        self.app_id = os.getenv('KUAIMAI_APP_ID')
        self.app_secret = os.getenv('KUAIMAI_APP_SECRET')
        self.api_url = 'https://cloud.kuaimai.com/api'

    def print_image(
        self,
        printer_id: str,
        image_base64: str,
        copies: int = 1
    ) -> Dict:
        """
        Print base64 encoded image

        API: tsplXmlWrite

        Returns: {
            'success': bool,
            'job_id': str,
            'message': str
        }
        """

    def _generate_sign(self, params: Dict) -> str:
        """Generate MD5 signature for API request"""

    def list_printers(self) -> List[Dict]:
        """Get list of available printers"""

    def get_print_status(self, job_id: str) -> Dict:
        """Check printing status"""
```

**Authentication**:
- Kuaimai uses MD5 signature
- Sign = MD5(appSecret + sorted_params_string + appSecret)
- Include appId, timestamp in all requests

### 2. API Routes

#### New Endpoint
**File**: `app/routes/shipping_batch_api.py`

```python
@bp.route('/shipping-batch/print-waybills', methods=['POST'])
def batch_print_waybills():
    """
    Batch print SF Express waybills

    Request: {
        'rental_ids': [1, 2, 3],
        'printer_id': 'printer_xxx' (optional)
    }

    Response: {
        'success': bool,
        'data': {
            'total': int,
            'success': int,
            'failed': int,
            'results': [...]
        }
    }
    """
```

#### Configuration Endpoint
```python
@bp.route('/shipping-batch/printers', methods=['GET'])
def list_printers():
    """Get list of available Kuaimai printers"""
```

### 3. Frontend Components

#### BatchShippingView Enhancement
**File**: `frontend/src/views/BatchShippingView.vue`

**New UI Elements**:
```vue
<div class="actions">
  <el-button @click="printAll" type="success">
    批量打印发货单
  </el-button>

  <!-- NEW -->
  <el-button
    @click="showWaybillPrintDialog"
    type="primary"
    :disabled="!hasWaybills"
  >
    <el-icon><Printer /></el-icon>
    批量打印快递面单 ({{ waybillCount }})
  </el-button>

  <el-button
    @click="showScheduleDialog"
    type="warning"
    :disabled="!hasWaybills"
  >
    预约发货 ({{ waybillCount }})
  </el-button>
</div>
```

**New Dialog**:
```vue
<el-dialog
  v-model="waybillPrintDialogVisible"
  title="批量打印快递面单"
  width="600px"
>
  <div class="waybill-print-form">
    <p>
      将为 <strong>{{ selectedWaybillCount }}</strong> 个订单打印面单
    </p>

    <el-form label-width="100px">
      <el-form-item label="选择打印机:">
        <el-select v-model="selectedPrinter" placeholder="请选择打印机">
          <el-option
            v-for="printer in printers"
            :key="printer.id"
            :label="printer.name"
            :value="printer.id"
          />
        </el-select>
      </el-form-item>
    </el-form>

    <!-- Progress during printing -->
    <el-progress
      v-if="printing"
      :percentage="printProgress"
      :status="printStatus"
    />

    <!-- Results after printing -->
    <div v-if="printResults" class="print-results">
      <el-alert
        :type="printResults.failed === 0 ? 'success' : 'warning'"
        :closable="false"
      >
        成功: {{ printResults.success }} / 失败: {{ printResults.failed }}
      </el-alert>

      <!-- Failed items details -->
      <div v-if="printResults.failed > 0" class="failed-items">
        <h4>失败详情：</h4>
        <ul>
          <li v-for="item in failedPrintItems" :key="item.rental_id">
            订单 {{ item.rental_id }}: {{ item.message }}
          </li>
        </ul>
      </div>
    </div>
  </div>

  <template #footer>
    <el-button @click="waybillPrintDialogVisible = false">
      取消
    </el-button>
    <el-button
      type="primary"
      @click="confirmPrintWaybills"
      :loading="printing"
      :disabled="!selectedPrinter"
    >
      {{ printing ? '打印中...' : '确认打印' }}
    </el-button>
  </template>
</el-dialog>
```

**New Methods**:
```typescript
const fetchPrinters = async () => {
  const response = await axios.get('/api/shipping-batch/printers')
  printers.value = response.data.data
}

const confirmPrintWaybills = async () => {
  const rentalIds = rentals.value
    .filter(r => r.ship_out_tracking_no && r.status !== 'shipped')
    .map(r => r.id)

  printing.value = true
  printProgress.value = 0

  try {
    const response = await axios.post('/api/shipping-batch/print-waybills', {
      rental_ids: rentalIds,
      printer_id: selectedPrinter.value
    })

    if (response.data.success) {
      printResults.value = response.data.data
      printProgress.value = 100
      printStatus.value =
        response.data.data.failed === 0 ? 'success' : 'warning'

      ElMessage.success(
        `打印完成: 成功${response.data.data.success}个`
      )
    }
  } catch (error) {
    ElMessage.error('打印失败')
  } finally {
    printing.value = false
  }
}
```

## Data Flow

### 1. Print Request Flow
```
User clicks "批量打印快递面单"
  ↓
Frontend: Show dialog, load printers
  ↓
User selects printer, confirms
  ↓
Frontend: POST /api/shipping-batch/print-waybills
  ↓
Backend: WaybillPrintService.batch_print_waybills()
  ↓
For each rental:
  1. Get waybill PDF from SF Express
  2. Convert PDF to images
  3. Encode images as base64
  4. Send to Kuaimai printer
  5. Track result
  ↓
Return aggregated results
  ↓
Frontend: Display success/failure summary
```

### 2. Error Handling Strategy

**Retry Logic**:
- SF API call: 2 retries with exponential backoff
- Kuaimai API call: 1 retry
- PDF conversion: No retry (fail fast)

**Partial Failure Handling**:
- Continue processing remaining items if one fails
- Return detailed results for each item
- Show summary with failed items highlighted

**Timeout Settings**:
- SF API: 30 seconds
- Kuaimai API: 20 seconds
- Total batch operation: 5 minutes max

## Configuration

### Environment Variables
```bash
# Kuaimai Cloud Printing
KUAIMAI_APP_ID=your_app_id
KUAIMAI_APP_SECRET=your_app_secret
KUAIMAI_DEFAULT_PRINTER_ID=printer_xxx  # Optional

# SF Express (already configured)
SF_PARTNER_ID=existing
SF_CHECKWORD=existing
```

### Docker Image Updates
Add to `requirements.txt`:
```
pdf2image>=1.16.0
```

No Dockerfile changes needed (poppler-utils already installed)

## Performance Considerations

### Optimization Strategies
1. **Parallel Processing**: Use ThreadPoolExecutor for concurrent API calls
2. **Caching**: Cache printer list for 5 minutes
3. **Lazy Loading**: Convert PDFs on-demand, don't pre-convert
4. **Connection Pooling**: Reuse HTTP connections for API calls

### Expected Performance
- Single waybill print: ~3-5 seconds
- Batch of 10 waybills: ~30-40 seconds (with parallelization)
- Memory usage: ~5MB per PDF during conversion

## Security Considerations

1. **API Credentials**: Store in environment variables, never commit
2. **Input Validation**: Validate rental_ids, printer_id
3. **Authorization**: Check user permissions before printing
4. **Rate Limiting**: Limit to 100 waybills per batch
5. **Logging**: Log all print operations for audit trail

## Testing Strategy

### Unit Tests
- `test_pdf_conversion_service.py`: PDF → Image conversion
- `test_kuaimai_service.py`: API signature generation, request formatting
- `test_waybill_print_service.py`: Orchestration logic

### Integration Tests
- Test with SF Express sandbox API
- Mock Kuaimai API responses
- Test error scenarios (network failures, invalid PDFs)

### Manual Testing Checklist
- [ ] Print single waybill
- [ ] Print batch of 10 waybills
- [ ] Handle printer offline scenario
- [ ] Handle SF API error
- [ ] Handle partial batch failure
- [ ] Verify image quality on physical printer

## Rollback Plan

If critical issues arise:
1. Feature flag to disable button in frontend
2. Environment variable to disable printing endpoint
3. Database migration not required (no schema changes)
4. Remove button from UI and disable route handler
