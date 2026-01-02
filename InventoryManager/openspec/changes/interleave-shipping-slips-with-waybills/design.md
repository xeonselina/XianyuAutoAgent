# Design: Interleave Shipping Slips with Waybills

## Context
当前系统已支持批量打印快递面单到快麦云打印机,但发货单需要单独通过Chrome浏览器打印。这导致装箱时需要手动匹配面单和发货单,效率低且容易出错。通过在快麦打印机上交替打印面单和发货单,可以大幅提升发货流程的效率和准确性。

## Goals / Non-Goals

**Goals:**
- 实现面单和发货单的交替打印
- 设计适配80mm热敏纸的精简发货单格式
- 确保条形码清晰可扫描
- 保持现有批量打印流程的稳定性

**Non-Goals:**
- 替换现有完整发货单模板
- 支持用户自定义发货单格式
- 实现发货单打印的独立入口
- 支持除快麦外的其他打印机

## Architecture Overview

### Current Flow (面单打印)
```
BatchShippingView (前端)
    ↓
POST /api/shipping/batch/print-waybills
    ↓
WaybillPrintService.print_batch_waybills()
    ↓
对于每个rental:
  1. SFExpressService.get_waybill_pdf()
  2. PDFConversionService.convert_pdf_to_base64_images()
  3. KuaimaiPrintService.print_image() [面单]
```

### New Flow (面单 + 发货单交替打印)
```
BatchShippingView (前端)
    ↓
POST /api/shipping/batch/print-waybills (参数: include_shipping_slips=true)
    ↓
WaybillPrintService.print_batch_waybills()
    ↓
对于每个rental:
  1. SFExpressService.get_waybill_pdf()
  2. PDFConversionService.convert_pdf_to_base64_images()
  3. KuaimaiPrintService.print_image() [面单]
  4. ShippingSlipImageService.generate_slip_image(rental) [新服务]
  5. KuaimaiPrintService.print_image() [发货单]
```

## Component Design

### 1. SimplifiedShippingSlip Component (前端)

**位置**: `frontend/src/components/printing/SimplifiedShippingSlip.vue`

**用途**: 无头渲染组件,用于生成发货单图像,不直接展示给用户

**布局设计** (80mm宽度):
```
┌─────────────────────────────────┐
│  [条形码]                       │  ← 订单识别码
│  订单号: RNT-12345             │
├─────────────────────────────────┤
│  收货人: 张三                   │
│  电话: 138****8888             │
│  地址: 广东省广州市天河区...    │
├─────────────────────────────────┤
│  设备: Sony A7M4               │
│  序列号: SN123456              │
│  附件: 电池x2, 存储卡64GB      │
├─────────────────────────────────┤
│  租期: 2025-01-10 ~ 2025-01-15 │
│  归还: 2025-01-15 16:00前      │
└─────────────────────────────────┘
```

**Props接口**:
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
  width: number  // 像素宽度,默认640px (80mm @ 203 DPI)
}
```

**样式要点**:
- 使用黑白配色,适配热敏打印
- 字体大小:标题14px,正文12px,说明10px
- 行高:1.4倍,确保可读性
- 条形码高度:40px,宽度自适应
- 整体高度自适应内容,最大不超过200mm

### 2. ShippingSlipImageService (后端)

**位置**: `app/services/printing/shipping_slip_image_service.py`

**职责**: 将发货单数据渲染为PNG图像

**方法**:
```python
class ShippingSlipImageService:
    def __init__(self, width_mm: int = 80, dpi: int = 203):
        """
        初始化服务
        width_mm: 纸张宽度(毫米)
        dpi: 打印分辨率
        """
        self.width_px = int(width_mm * dpi / 25.4)  # 转换为像素
        self.dpi = dpi

    def generate_slip_image(self, rental: Rental) -> str:
        """
        生成发货单图像

        Args:
            rental: 租赁记录对象

        Returns:
            str: base64编码的PNG图像

        Raises:
            SlipGenerationError: 生成失败时抛出
        """
        # 1. 准备数据
        data = self._prepare_data(rental)

        # 2. 调用前端渲染服务(通过Puppeteer/Playwright)
        html = self._render_template(data)

        # 3. 转换HTML为图像
        image_data = self._html_to_image(html)

        # 4. 返回base64
        return base64.b64encode(image_data).decode('utf-8')
```

**实现方案对比**:

#### 方案A: Puppeteer/Playwright (推荐)
- **优点**:
  - 可以直接渲染Vue组件,保持与前端一致
  - 支持复杂布局和样式
  - 图像质量高
- **缺点**:
  - 需要安装Node.js和浏览器驱动
  - 首次渲染较慢(约1-2秒)
- **适用场景**: 对图像质量要求高,可接受短暂延迟

#### 方案B: Python图像库(PIL/ReportLab)
- **优点**:
  - 纯Python实现,无外部依赖
  - 渲染速度快(< 100ms)
- **缺点**:
  - 需要手动绘制布局,代码复杂
  - 难以复用前端组件
  - 样式调整不灵活
- **适用场景**: 追求性能,布局简单固定

**推荐选择**: 方案A(Puppeteer)
- 理由: 发货单布局相对复杂,且批量打印场景下1-2秒延迟可接受

### 3. API Endpoint

**路由**: `POST /api/shipping/generate-slip-image`

**请求参数**:
```json
{
  "rental_id": 123
}
```

**响应**:
```json
{
  "success": true,
  "image_base64": "iVBORw0KGgoAAAANS...",
  "rental_id": 123
}
```

**错误响应**:
```json
{
  "success": false,
  "error": "租赁记录不存在",
  "rental_id": 123
}
```

## Data Flow

### 交替打印流程

```python
def print_batch_waybills(rental_ids: List[int], include_shipping_slips: bool = True):
    results = []

    for rental_id in rental_ids:
        try:
            # 1. 打印面单
            waybill_result = print_single_waybill(rental_id)
            if not waybill_result['success']:
                results.append({
                    'rental_id': rental_id,
                    'waybill_success': False,
                    'slip_success': False,
                    'error': waybill_result['message']
                })
                continue

            # 2. 打印发货单(如果启用)
            slip_result = {'success': True}
            if include_shipping_slips:
                slip_result = print_single_shipping_slip(rental_id)

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
            logger.error(f"打印失败: Rental {rental_id}, 错误: {e}")
            results.append({
                'rental_id': rental_id,
                'waybill_success': False,
                'slip_success': False,
                'error': str(e)
            })

    return results

def print_single_shipping_slip(rental_id: int) -> Dict:
    """打印单个发货单"""
    # 1. 生成发货单图像
    image_base64 = slip_image_service.generate_slip_image(rental_id)

    # 2. 发送到快麦打印
    result = kuaimai_service.print_image(
        base64_image=image_base64,
        copies=1
    )

    return result
```

## Performance Considerations

### 打印速度优化

**当前面单打印时间**(单张):
- 获取PDF: 500-800ms
- 转换图像: 200-300ms
- 发送打印: 100-200ms
- **总计: 约1秒**

**新增发货单时间**(单张):
- 生成图像: 1000-1500ms (Puppeteer首次)
- 发送打印: 100-200ms
- **总计: 约1.2秒**

**批量打印10单的总时间**:
- 当前: 10秒
- 新增发货单后: 22秒
- **增加约120%时间,但仍在可接受范围内**

**优化策略**:
1. **预热Puppeteer**: 应用启动时预先启动浏览器实例
2. **并行生成**: 在等待面单打印时,并行生成下一张发货单图像
3. **缓存模板**: 缓存渲染好的HTML模板,减少重复渲染

### 内存管理

**Puppeteer内存占用**:
- 浏览器实例: 约150MB
- 单次渲染: 约20-30MB
- **建议**: 使用单一共享浏览器实例,渲染后立即关闭页面

**图像数据**:
- 单张发货单PNG: 约50-100KB
- 批量打印10单: 约1MB
- **策略**: 生成后立即发送到打印机,不保留在内存中

## Error Handling

### 错误分类和处理

| 错误类型 | 处理策略 | 用户体验 |
|---------|---------|---------|
| 发货单生成失败 | 跳过该单,继续打印其他 | 提示哪些订单缺少发货单 |
| 快麦API限流 | 等待后重试(最多3次) | 显示"打印中,请稍候" |
| 快麦打印失败 | 记录失败订单ID | 提示用户补打失败的单据 |
| Puppeteer超时 | 使用备用方案(PIL绘制) | 发货单格式简化但可用 |

### 日志记录

```python
# 关键日志点
logger.info(f"开始批量打印: {len(rental_ids)}个订单")
logger.info(f"Rental {rental_id}: 开始打印面单")
logger.info(f"Rental {rental_id}: 面单打印成功, JobID: {job_id}")
logger.info(f"Rental {rental_id}: 开始生成发货单图像")
logger.info(f"Rental {rental_id}: 发货单图像生成成功, 大小: {size}KB")
logger.info(f"Rental {rental_id}: 发货单打印成功, JobID: {job_id}")
logger.error(f"Rental {rental_id}: 发货单生成失败, 错误: {error}")
logger.info(f"批量打印完成: 成功{success_count}/{total_count}")
```

## UI/UX Considerations

### 批量打印对话框更新

**新增选项**:
```vue
<el-checkbox v-model="includeSh ippingSlips">
  同时打印发货单
</el-checkbox>
```

**默认值**: 启用(checked)

**提示信息**:
```
打印顺序: 面单 → 发货单 → 面单 → 发货单 ...
预计时间: 约 {estimatedTime} 秒
```

### 进度显示

```
正在打印第 3/10 单...
✓ 订单 #123: 面单已打印
✓ 订单 #123: 发货单已打印
✓ 订单 #124: 面单已打印
⏳ 订单 #124: 正在打印发货单...
```

## Testing Strategy

### 单元测试
- `ShippingSlipImageService.generate_slip_image()`: 测试图像生成
- 条形码正确性: 扫描验证生成的条形码
- 数据映射: 确保所有必要信息都包含在图像中

### 集成测试
- 端到端打印流程: 从API调用到快麦打印完成
- 错误处理: 模拟各种失败场景
- 打印顺序: 验证交替打印的顺序正确性

### 手动测试
- 单张打印测试
- 批量打印测试(1单/5单/10单/20单)
- 条形码扫描测试
- 打印质量检查(清晰度、对齐、裁切)

## Migration & Rollback

### 功能开关
添加环境变量控制:
```
ENABLE_SHIPPING_SLIP_PRINT=true
```

### 向后兼容
- 默认不启用发货单打印,需用户勾选
- 现有单独打印发货单功能保持不变
- API参数`include_shipping_slips`默认为false

### 回滚计划
如果出现严重问题:
1. 设置 `ENABLE_SHIPPING_SLIP_PRINT=false`
2. 前端隐藏"同时打印发货单"选项
3. 系统回退到仅打印面单的模式

## Open Questions

### Q1: 是否需要支持单独打印发货单?
**回答**: 暂不支持。用户仍可使用现有的Chrome打印方式单独打印完整发货单。精简发货单仅用于批量打印场景。

### Q2: 发货单打印失败时,是否阻止面单打印?
**回答**: 不阻止。发货单打印失败时,记录错误但继续打印其他订单。最后汇总显示哪些订单缺少发货单,用户可单独补打。

### Q3: 如何处理快麦打印机离线的情况?
**回答**: 快麦API会返回打印机离线错误。系统应提前检测打印机状态,离线时提示用户检查设备,不发起打印任务。

## Future Enhancements (Out of Scope)

1. **自定义发货单模板**: 允许用户配置显示哪些字段
2. **打印预览**: 批量打印前预览发货单样式
3. **打印历史**: 记录所有打印任务的详细日志
4. **补打功能**: 快速补打失败的发货单
5. **多语言发货单**: 支持英文等其他语言
