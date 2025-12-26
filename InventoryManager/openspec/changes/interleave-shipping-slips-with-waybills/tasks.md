# Tasks: Interleave Shipping Slips with Waybills

## Phase 1: Frontend - Simplified Shipping Slip Component

### Task 1.1: Create SimplifiedShippingSlip.vue component
- [ ] Create file: `frontend/src/components/printing/SimplifiedShippingSlip.vue`
- [ ] Define Props interface:
  ```typescript
  interface Props {
    rental: {
      id: number
      customer_name: string
      customer_phone: string
      destination: string
      device: {
        name: string
        serial_number: string
        device_model?: { name: string }
      }
      accessories: Array<{
        name: string
        model: string
      }>
      start_date: string
      end_date: string
    }
    width?: number  // Default: 640px (80mm @ 203 DPI)
  }
  ```
- [ ] Install barcode library: `npm install jsbarcode --save`
- [ ] Import JsBarcode in component

**Validation**:
- Component accepts rental prop without errors
- TypeScript types are correct

### Task 1.2: Implement barcode generation
- [ ] Add template element for barcode:
  ```vue
  <svg ref="barcodeRef" class="barcode"></svg>
  ```
- [ ] Add barcode generation logic in `onMounted`:
  ```typescript
  import { onMounted, ref } from 'vue'
  import JsBarcode from 'jsbarcode'

  const barcodeRef = ref<SVGElement>()

  onMounted(() => {
    if (barcodeRef.value) {
      JsBarcode(barcodeRef.value, `RNT-${props.rental.id}`, {
        format: 'CODE128',
        height: 40,
        width: 2,
        displayValue: false,
        margin: 10
      })
    }
  })
  ```

**Validation**:
- Barcode renders correctly with rental ID
- SVG element has proper dimensions

### Task 1.3: Design 80mm thermal paper layout
- [ ] Create template structure:
  ```vue
  <div class="simplified-slip" :style="{ width: `${width}px` }">
    <!-- Barcode section -->
    <div class="barcode-section">
      <svg ref="barcodeRef" class="barcode"></svg>
      <div class="order-number">订单号: RNT-{{ rental.id }}</div>
    </div>

    <!-- Customer info section -->
    <div class="section customer-section">
      <div class="info-row">
        <span class="label">收货人:</span>
        <span class="value">{{ rental.customer_name }}</span>
      </div>
      <div class="info-row">
        <span class="label">电话:</span>
        <span class="value">{{ maskPhone(rental.customer_phone) }}</span>
      </div>
      <div class="info-row">
        <span class="label">地址:</span>
        <span class="value">{{ rental.destination || '未知' }}</span>
      </div>
    </div>

    <!-- Device info section -->
    <div class="section device-section">
      <div class="info-row">
        <span class="label">设备:</span>
        <span class="value">{{ rental.device.name }}</span>
      </div>
      <div class="info-row">
        <span class="label">序列号:</span>
        <span class="value">{{ rental.device.serial_number }}</span>
      </div>
      <div class="info-row" v-if="hasAccessories">
        <span class="label">附件:</span>
        <span class="value">{{ accessoriesSummary }}</span>
      </div>
    </div>

    <!-- Rental period section -->
    <div class="section period-section">
      <div class="info-row">
        <span class="label">租期:</span>
        <span class="value">{{ rental.start_date }} ~ {{ rental.end_date }}</span>
      </div>
      <div class="info-row">
        <span class="label">归还:</span>
        <span class="value highlight">{{ rental.end_date }} 16:00前</span>
      </div>
    </div>
  </div>
  ```

**Validation**:
- Layout matches design in design.md
- All required fields are displayed

### Task 1.4: Implement utility functions
- [ ] Add phone masking function:
  ```typescript
  const maskPhone = (phone: string) => {
    if (!phone || phone.length < 11) return phone
    return phone.slice(0, 3) + '****' + phone.slice(-4)
  }
  ```
- [ ] Add accessories summary computed property:
  ```typescript
  const hasAccessories = computed(() => {
    return props.rental.accessories && props.rental.accessories.length > 0
  })

  const accessoriesSummary = computed(() => {
    if (!hasAccessories.value) return ''
    return props.rental.accessories
      .map(acc => `${acc.name}${acc.model ? ` ${acc.model}` : ''}`)
      .join(', ')
  })
  ```

**Validation**:
- Phone number is correctly masked: 138****5678
- Accessories display as comma-separated list

### Task 1.5: Add thermal printer CSS styles
- [ ] Add scoped styles:
  ```vue
  <style scoped>
  .simplified-slip {
    background: white;
    font-family: 'Arial', 'Helvetica', '微软雅黑', sans-serif;
    color: black;
    padding: 8px;
    box-sizing: border-box;
  }

  .barcode-section {
    text-align: center;
    margin-bottom: 8px;
    padding-bottom: 8px;
    border-bottom: 1px dashed #000;
  }

  .barcode {
    width: 100%;
    max-width: 300px;
  }

  .order-number {
    font-size: 12px;
    font-weight: bold;
    margin-top: 4px;
  }

  .section {
    margin-bottom: 8px;
    padding-bottom: 8px;
    border-bottom: 1px dashed #000;
  }

  .section:last-child {
    border-bottom: none;
  }

  .info-row {
    display: flex;
    margin-bottom: 4px;
    font-size: 12px;
    line-height: 1.4;
  }

  .label {
    min-width: 60px;
    font-weight: 500;
    flex-shrink: 0;
  }

  .value {
    flex: 1;
    word-break: break-all;
  }

  .value.highlight {
    font-weight: bold;
  }

  .period-section .value.highlight {
    color: #e74c3c;
  }
  </style>
  ```

**Validation**:
- Text is black and white only
- Layout fits within 80mm width
- Print preview shows clear, readable text

## Phase 2: Backend - Image Generation Service

### Task 2.1: Install Puppeteer
- [ ] Add Puppeteer to backend requirements:
  ```bash
  cd /Users/jimmypan/git_repo/XianyuAutoAgent/InventoryManager
  pip install pyppeteer==1.0.2
  ```
- [ ] Download Chromium browser:
  ```bash
  python -m pyppeteer.chromium_downloader
  ```
- [ ] Verify installation:
  ```python
  from pyppeteer import launch
  import asyncio

  async def test():
      browser = await launch()
      await browser.close()

  asyncio.run(test())
  ```

**Validation**:
- Pyppeteer imports without errors
- Chromium browser downloads successfully

### Task 2.2: Create ShippingSlipImageService
- [ ] Create file: `app/services/printing/shipping_slip_image_service.py`
- [ ] Define service class:
  ```python
  import base64
  import asyncio
  from typing import Optional
  from pyppeteer import launch
  from app.models import Rental
  from app import db

  class SlipGenerationError(Exception):
      """发货单生成失败异常"""
      pass

  class ShippingSlipImageService:
      def __init__(self, width_mm: int = 80, dpi: int = 203):
          self.width_px = int(width_mm * dpi / 25.4)
          self.dpi = dpi
          self._browser = None

      async def _get_browser(self):
          """获取或创建共享浏览器实例"""
          if self._browser is None or not self._browser.process.poll() is None:
              self._browser = await launch(headless=True, args=['--no-sandbox'])
          return self._browser

      async def _close_browser(self):
          """关闭浏览器实例"""
          if self._browser:
              await self._browser.close()
              self._browser = None
  ```

**Validation**:
- Class instantiates without errors
- Browser singleton pattern works

### Task 2.3: Implement data preparation
- [ ] Add `_prepare_data` method:
  ```python
  def _prepare_data(self, rental: Rental) -> dict:
      """准备发货单数据"""
      return {
          'id': rental.id,
          'customer_name': rental.customer_name or '未填写',
          'customer_phone': rental.customer_phone or '',
          'destination': rental.destination or '未知',
          'device': {
              'name': rental.device.name if rental.device else '未知设备',
              'serial_number': rental.device.serial_number if rental.device else '',
          },
          'accessories': [
              {'name': acc.name, 'model': acc.model or ''}
              for acc in (rental.accessories or [])
          ],
          'start_date': rental.start_date.strftime('%Y-%m-%d') if rental.start_date else '',
          'end_date': rental.end_date.strftime('%Y-%m-%d') if rental.end_date else '',
      }
  ```

**Validation**:
- Method handles null values gracefully
- Returns properly formatted dict

### Task 2.4: Implement HTML rendering
- [ ] Add `_render_template` method:
  ```python
  def _render_template(self, data: dict) -> str:
      """渲染Vue组件为HTML字符串"""
      # 读取SimplifiedShippingSlip.vue编译后的HTML
      # 这里需要前端配合提供一个渲染端点或静态HTML
      # 简化方案: 直接用Jinja2模板渲染类似布局

      from jinja2 import Template

      template_str = """
      <!DOCTYPE html>
      <html>
      <head>
          <meta charset="UTF-8">
          <style>
              body { margin: 0; padding: 0; }
              .simplified-slip { /* 复制CSS样式 */ }
              /* ... 其他样式 ... */
          </style>
      </head>
      <body>
          <div class="simplified-slip" style="width: {{ width }}px">
              <!-- 复制Vue模板结构,使用Jinja2语法 -->
          </div>
          <script src="https://cdn.jsdelivr.net/npm/jsbarcode@3.11.5/dist/JsBarcode.all.min.js"></script>
          <script>
              JsBarcode("#barcode", "RNT-{{ data.id }}", {
                  format: "CODE128",
                  height: 40,
                  width: 2,
                  displayValue: false
              });
          </script>
      </body>
      </html>
      """

      template = Template(template_str)
      return template.render(data=data, width=self.width_px)
  ```

**Validation**:
- HTML renders correctly with rental data
- Barcode script executes in browser context

### Task 2.5: Implement HTML to image conversion
- [ ] Add `_html_to_image` method:
  ```python
  async def _html_to_image(self, html: str) -> bytes:
      """将HTML转换为PNG图像"""
      browser = await self._get_browser()
      page = await browser.newPage()

      try:
          await page.setViewport({'width': self.width_px, 'height': 800})
          await page.setContent(html)

          # 等待条形码渲染完成
          await page.waitForSelector('.barcode svg', timeout=3000)
          await asyncio.sleep(0.5)  # 额外等待确保渲染完成

          # 截图
          element = await page.querySelector('.simplified-slip')
          screenshot = await element.screenshot(type='png')

          return screenshot

      except Exception as e:
          raise SlipGenerationError(f"HTML转图像失败: {str(e)}")

      finally:
          await page.close()
  ```

**Validation**:
- Screenshot captures full slip content
- Image quality is clear and readable

### Task 2.6: Implement main generate method
- [ ] Add `generate_slip_image` method:
  ```python
  def generate_slip_image(self, rental_id: int) -> str:
      """
      生成发货单图像

      Args:
          rental_id: 租赁记录ID

      Returns:
          str: base64编码的PNG图像

      Raises:
          SlipGenerationError: 生成失败时抛出
      """
      # 查询租赁记录
      rental = db.session.get(Rental, rental_id)
      if not rental:
          raise SlipGenerationError(f"租赁记录不存在: ID {rental_id}")

      # 准备数据
      data = self._prepare_data(rental)

      # 渲染HTML
      html = self._render_template(data)

      # 转换为图像 (使用asyncio运行异步函数)
      loop = asyncio.new_event_loop()
      asyncio.set_event_loop(loop)
      try:
          image_data = loop.run_until_complete(self._html_to_image(html))
      finally:
          loop.close()

      # 编码为base64
      return base64.b64encode(image_data).decode('utf-8')
  ```

**Validation**:
- Method completes without errors for valid rental ID
- Returns valid base64 string
- Raises SlipGenerationError for invalid ID

### Task 2.7: Add service singleton instance
- [ ] In `app/services/__init__.py`, add:
  ```python
  from app.services.printing.shipping_slip_image_service import ShippingSlipImageService

  # 全局单例
  shipping_slip_image_service = ShippingSlipImageService(width_mm=80, dpi=203)
  ```

**Validation**:
- Service can be imported from other modules
- Browser instance is shared across requests

## Phase 3: Backend - API Endpoint

### Task 3.1: Create API route
- [ ] Create file: `app/api/printing.py` (or add to existing shipping API file)
- [ ] Define endpoint:
  ```python
  from flask import Blueprint, request, jsonify
  from app.services import shipping_slip_image_service
  from app.services.printing.shipping_slip_image_service import SlipGenerationError

  printing_bp = Blueprint('printing', __name__)

  @printing_bp.route('/shipping/generate-slip-image', methods=['POST'])
  def generate_slip_image():
      """生成发货单图像"""
      try:
          data = request.get_json()
          rental_id = data.get('rental_id')

          if not rental_id:
              return jsonify({
                  'success': False,
                  'error': '缺少必要参数: rental_id'
              }), 400

          # 生成图像
          image_base64 = shipping_slip_image_service.generate_slip_image(rental_id)

          return jsonify({
              'success': True,
              'image_base64': image_base64,
              'rental_id': rental_id
          })

      except SlipGenerationError as e:
          return jsonify({
              'success': False,
              'error': str(e),
              'rental_id': rental_id
          }), 400

      except Exception as e:
          logger.exception(f"生成发货单图像失败: {e}")
          return jsonify({
              'success': False,
              'error': '服务器内部错误'
          }), 500
  ```

**Validation**:
- Endpoint returns 200 with valid rental_id
- Endpoint returns 400 with invalid rental_id
- Response JSON matches spec format

### Task 3.2: Register blueprint
- [ ] In `app/__init__.py`, register the blueprint:
  ```python
  from app.api.printing import printing_bp
  app.register_blueprint(printing_bp, url_prefix='/api')
  ```

**Validation**:
- Route is accessible at `/api/shipping/generate-slip-image`
- Swagger/API docs (if exists) update automatically

## Phase 4: Integration - Batch Print Flow

### Task 4.1: Update WaybillPrintService
- [ ] Open `app/services/shipping/waybill_print_service.py`
- [ ] Add `include_shipping_slips` parameter to `print_batch_waybills`:
  ```python
  def print_batch_waybills(
      self,
      rental_ids: List[int],
      include_shipping_slips: bool = True
  ) -> List[dict]:
      """
      批量打印快递面单(可选交替打印发货单)

      Args:
          rental_ids: 租赁记录ID列表
          include_shipping_slips: 是否同时打印发货单

      Returns:
          List[dict]: 打印结果列表
      """
  ```

**Validation**:
- Method signature updated correctly
- Default value is `True`

### Task 4.2: Implement interleaved printing logic
- [ ] Modify loop in `print_batch_waybills`:
  ```python
  from app.services import shipping_slip_image_service
  from app.services.printing.kuaimai_service import kuaimai_service

  results = []

  for rental_id in rental_ids:
      try:
          # 1. 打印面单
          logger.info(f"Rental {rental_id}: 开始打印面单")
          waybill_result = self.print_single_waybill(rental_id)

          if not waybill_result['success']:
              results.append({
                  'rental_id': rental_id,
                  'waybill_success': False,
                  'slip_success': False,
                  'error': waybill_result.get('message', '面单打印失败')
              })
              continue

          logger.info(f"Rental {rental_id}: 面单打印成功")

          # 2. 打印发货单(如果启用)
          slip_result = {'success': True, 'job_id': None}
          if include_shipping_slips:
              logger.info(f"Rental {rental_id}: 开始生成发货单图像")
              slip_result = self._print_single_shipping_slip(rental_id)

              if slip_result['success']:
                  logger.info(f"Rental {rental_id}: 发货单打印成功, JobID: {slip_result.get('job_id')}")
              else:
                  logger.error(f"Rental {rental_id}: 发货单打印失败, 错误: {slip_result.get('error')}")

          results.append({
              'rental_id': rental_id,
              'waybill_success': True,
              'slip_success': slip_result['success'],
              'slip_error': slip_result.get('error'),
              'job_ids': {
                  'waybill': waybill_result.get('job_ids'),
                  'slip': slip_result.get('job_id')
              }
          })

      except Exception as e:
          logger.exception(f"打印失败: Rental {rental_id}")
          results.append({
              'rental_id': rental_id,
              'waybill_success': False,
              'slip_success': False,
              'error': str(e)
          })

  # 汇总统计
  total = len(rental_ids)
  waybill_success = sum(1 for r in results if r.get('waybill_success'))
  slip_success = sum(1 for r in results if r.get('slip_success'))

  logger.info(f"批量打印完成: 面单 {waybill_success}/{total}, 发货单 {slip_success}/{total}")

  return results
  ```

**Validation**:
- Print order is correct: waybill → slip → waybill → slip
- Failed waybill skips corresponding slip
- Failed slip doesn't prevent next waybill

### Task 4.3: Implement _print_single_shipping_slip helper
- [ ] Add private method:
  ```python
  def _print_single_shipping_slip(self, rental_id: int) -> dict:
      """打印单个发货单"""
      try:
          # 生成发货单图像
          image_base64 = shipping_slip_image_service.generate_slip_image(rental_id)

          # 发送到快麦打印
          result = kuaimai_service.print_image(
              base64_image=image_base64,
              copies=1
          )

          return result

      except SlipGenerationError as e:
          return {'success': False, 'error': str(e)}

      except Exception as e:
          logger.exception(f"发货单打印异常: Rental {rental_id}")
          return {'success': False, 'error': f'打印异常: {str(e)}'}
  ```

**Validation**:
- Method successfully generates and prints slip
- Exceptions are caught and returned as error dict

### Task 4.4: Update API route parameter
- [ ] Find the existing batch print API endpoint (likely in `app/api/shipping.py`)
- [ ] Add `include_shipping_slips` parameter to request body:
  ```python
  @shipping_bp.route('/batch/print-waybills', methods=['POST'])
  def batch_print_waybills():
      data = request.get_json()
      rental_ids = data.get('rental_ids', [])
      include_shipping_slips = data.get('include_shipping_slips', True)

      results = waybill_print_service.print_batch_waybills(
          rental_ids=rental_ids,
          include_shipping_slips=include_shipping_slips
      )

      return jsonify({'success': True, 'results': results})
  ```

**Validation**:
- API accepts `include_shipping_slips` parameter
- Parameter defaults to `True`

## Phase 5: Frontend - UI Integration

### Task 5.1: Update BatchShippingView dialog
- [ ] Open the batch shipping view component (find using `Glob` tool)
- [ ] Add checkbox to dialog template:
  ```vue
  <el-dialog title="批量打印" v-model="printDialogVisible">
      <div class="dialog-content">
          <p>已选择 {{ selectedRentals.length }} 个订单</p>

          <el-checkbox v-model="includeSh ippingSlips">
              同时打印发货单
          </el-checkbox>

          <div class="tip-text">
              打印顺序: 面单 → 发货单 → 面单 → 发货单 ...
          </div>
      </div>

      <template #footer>
          <el-button @click="printDialogVisible = false">取消</el-button>
          <el-button type="primary" @click="confirmBatchPrint">确认打印</el-button>
      </template>
  </el-dialog>
  ```
- [ ] Add reactive variable in script:
  ```typescript
  const includeShippingSlips = ref(true)
  ```

**Validation**:
- Checkbox appears in dialog
- Default state is checked

### Task 5.2: Update API call to include parameter
- [ ] Modify `confirmBatchPrint` method:
  ```typescript
  const confirmBatchPrint = async () => {
      try {
          loading.value = true

          const response = await axios.post('/api/shipping/batch/print-waybills', {
              rental_ids: selectedRentalIds.value,
              include_shipping_slips: includeShippingSlips.value
          })

          // 处理响应...
          handlePrintResults(response.data.results)

      } catch (error) {
          ElMessage.error('批量打印失败')
      } finally {
          loading.value = false
      }
  }
  ```

**Validation**:
- API receives correct `include_shipping_slips` value
- Request payload includes the parameter

### Task 5.3: Enhance progress display
- [ ] Update progress message to distinguish waybill and slip:
  ```typescript
  const handlePrintResults = (results) => {
      const total = results.length
      const waybillSuccess = results.filter(r => r.waybill_success).length
      const slipSuccess = results.filter(r => r.slip_success).length

      let message = `打印完成: 面单 ${waybillSuccess}/${total}`

      if (includeShippingSlips.value) {
          message += `, 发货单 ${slipSuccess}/${total}`
      }

      ElMessage.success(message)

      // 显示失败详情
      const failures = results.filter(r => !r.waybill_success || !r.slip_success)
      if (failures.length > 0) {
          showFailureDetails(failures)
      }
  }
  ```

**Validation**:
- Success message shows both waybill and slip counts
- Failure details are displayed correctly

## Phase 6: Testing

### Task 6.1: Unit test - SimplifiedShippingSlip component
- [ ] Create test file: `frontend/tests/unit/SimplifiedShippingSlip.spec.ts`
- [ ] Test barcode generation
- [ ] Test phone masking function
- [ ] Test accessories summary computation
- [ ] Test null/empty value handling

**Pass Criteria**:
- All unit tests pass
- Code coverage > 80%

### Task 6.2: Unit test - ShippingSlipImageService
- [ ] Create test file: `tests/test_shipping_slip_image_service.py`
- [ ] Test `_prepare_data` with complete rental
- [ ] Test `_prepare_data` with null values
- [ ] Test `generate_slip_image` with valid ID
- [ ] Test `generate_slip_image` with invalid ID
- [ ] Test exception handling

**Pass Criteria**:
- All tests pass
- Exceptions are properly raised

### Task 6.3: Integration test - API endpoint
- [ ] Test POST `/api/shipping/generate-slip-image` with valid rental_id
- [ ] Test with invalid rental_id
- [ ] Test with missing rental_id parameter
- [ ] Verify response format matches spec

**Pass Criteria**:
- All status codes correct (200, 400, 500)
- Response JSON structure matches spec

### Task 6.4: Integration test - Batch print flow
- [ ] Create 3 test rentals in database
- [ ] Call `print_batch_waybills` with `include_shipping_slips=True`
- [ ] Verify results contain both waybill and slip success flags
- [ ] Verify print order (check logs or mock Kuaimai service)

**Pass Criteria**:
- Interleaved printing works correctly
- Results structure matches specification

### Task 6.5: Manual test - End-to-end printing
- [ ] Set up Kuaimai printer connection
- [ ] Create 5 test rental orders with complete data
- [ ] Batch print with "同时打印发货单" checked
- [ ] Verify physical print output:
  - Correct print order (alternating waybill and slip)
  - Barcode is scannable
  - Text is clear and readable
  - Layout fits on 80mm paper
  - No truncation or overflow

**Pass Criteria**:
- All 10 documents print successfully
- Print quality meets requirements
- Barcode scans correctly

### Task 6.6: Manual test - Error scenarios
- [ ] Test with printer offline
- [ ] Test with invalid rental data (missing device)
- [ ] Test with very long address (>100 characters)
- [ ] Test with empty accessories list
- [ ] Test batch print with "同时打印发货单" unchecked

**Pass Criteria**:
- Errors are handled gracefully
- System doesn't crash
- User receives clear error messages

### Task 6.7: Performance test
- [ ] Create 20 test rentals
- [ ] Measure batch print time with shipping slips enabled
- [ ] Measure batch print time with shipping slips disabled (baseline)
- [ ] Monitor memory usage during printing
- [ ] Verify no memory leaks after 50 print jobs

**Pass Criteria**:
- 20 orders complete within 60 seconds
- Memory usage stable (< 500MB increase)
- No Puppeteer browser crashes

## Phase 7: Documentation and Deployment

### Task 7.1: Update API documentation
- [ ] Document new `include_shipping_slips` parameter in Swagger/OpenAPI spec (if exists)
- [ ] Add example request/response for `/api/shipping/generate-slip-image`

### Task 7.2: Update user guide (if exists)
- [ ] Add section explaining "同时打印发货单" feature
- [ ] Include screenshot of checkbox in dialog
- [ ] Explain simplified shipping slip format

### Task 7.3: Add feature toggle
- [ ] Add environment variable in `.env.example`:
  ```
  ENABLE_SHIPPING_SLIP_PRINT=true
  ```
- [ ] Wrap feature with toggle in backend:
  ```python
  import os
  ENABLE_SHIPPING_SLIP_PRINT = os.getenv('ENABLE_SHIPPING_SLIP_PRINT', 'true').lower() == 'true'

  if include_shipping_slips and not ENABLE_SHIPPING_SLIP_PRINT:
      include_shipping_slips = False
  ```

**Validation**:
- Feature can be disabled via environment variable
- System gracefully falls back to waybills-only mode

### Task 7.4: Create deployment checklist
- [ ] Update production requirements.txt with pyppeteer
- [ ] Ensure Chromium downloads on production server
- [ ] Test Puppeteer in production environment (Docker/server)
- [ ] Configure Kuaimai printer access
- [ ] Verify thermal paper is 80mm width
- [ ] Run smoke test: Print 1 order with shipping slip

### Task 7.5: Monitor and rollback plan
- [ ] Add logging for print job metrics (success rate, latency)
- [ ] Set up alert for high failure rate (>20%)
- [ ] Document rollback procedure:
  1. Set `ENABLE_SHIPPING_SLIP_PRINT=false`
  2. Restart backend service
  3. Verify system returns to waybills-only mode

## Completion Checklist

Before marking this change as complete:
- [ ] All frontend tasks completed (Tasks 1.1 - 1.5)
- [ ] All backend tasks completed (Tasks 2.1 - 2.7, 3.1 - 3.2)
- [ ] Integration tasks completed (Tasks 4.1 - 4.4)
- [ ] UI tasks completed (Tasks 5.1 - 5.3)
- [ ] All automated tests pass (Tasks 6.1 - 6.4)
- [ ] Manual testing completed successfully (Tasks 6.5 - 6.7)
- [ ] Documentation updated (Tasks 7.1 - 7.2)
- [ ] Deployment preparation complete (Tasks 7.3 - 7.5)
- [ ] Code reviewed and approved
- [ ] Feature tested in staging environment
- [ ] Performance meets requirements (≤30s for 10 orders)
- [ ] No console errors or warnings
- [ ] `openspec validate --strict` passes
