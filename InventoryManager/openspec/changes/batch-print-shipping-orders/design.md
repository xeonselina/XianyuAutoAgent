# Design Document: 批量打印发货单

## Architecture Overview

批量打印功能采用简单的客户端渲染 + 浏览器打印方案，避免引入复杂的后端打印服务或 PDF 生成库。

```
用户操作流程：
甘特图 → 批量打印对话框 → 选择日期范围 → 批量打印视图 → 浏览器打印
   ↓           ↓                 ↓                 ↓              ↓
GanttChart  BatchPrintDialog   API Query    BatchShippingOrderView  window.print()
```

## Component Design

### 1. BatchPrintDialog (对话框组件)

**职责**：
- 接收用户输入的日期范围
- 预览待打印订单列表
- 验证输入并导航到批量打印视图

**Props**：
- `modelValue: boolean` - 对话框显示状态

**Emits**：
- `update:modelValue` - 关闭对话框
- `confirm: { startDate: string, endDate: string }` - 确认打印

**State**：
```typescript
{
  startDate: Date | null,
  endDate: Date | null,
  previewOrders: Rental[],
  loading: boolean,
  error: string | null
}
```

**Methods**：
- `handlePreview()` - 调用 API 预览订单
- `handleConfirm()` - 跳转到批量打印视图
- `validateDateRange()` - 验证日期范围有效性

### 2. BatchShippingOrderView (批量打印视图)

**职责**：
- 根据日期范围查询租赁记录
- 渲染多个发货单
- 提供打印功能

**URL Parameters**：
- `start_date: string` (YYYY-MM-DD)
- `end_date: string` (YYYY-MM-DD)

**State**：
```typescript
{
  rentals: Rental[],
  loading: boolean,
  error: string | null,
  validationWarnings: { rentalId: number, issues: string[] }[]
}
```

**Methods**：
- `fetchRentals()` - 批量查询租赁记录
- `validateRentals()` - 验证数据完整性
- `handlePrint()` - 触发浏览器打印
- `goBack()` - 返回甘特图

**Template Structure**：
```vue
<div class="batch-shipping-order-page">
  <!-- 操作栏 (不打印) -->
  <div class="action-bar print-hide">
    <el-button @click="goBack">返回</el-button>
    <span>共 {{ rentals.length }} 个订单</span>
    <el-button @click="handlePrint">打印所有</el-button>
  </div>

  <!-- 发货单列表 (打印) -->
  <div v-for="rental in rentals" :key="rental.id"
       class="shipping-order-page-wrapper">
    <!-- 复用 ShippingOrderView 的内容结构 -->
    <ShippingOrderContent :rental="rental" />
  </div>
</div>
```

## API Design

### Endpoint: GET /api/rentals/by-ship-date

**Purpose**: 根据发货日期范围查询待发货租赁记录

**Request**:
```
GET /api/rentals/by-ship-date?start_date=2025-01-01&end_date=2025-01-31
```

**Query Parameters**:
- `start_date` (required): 开始日期，格式 YYYY-MM-DD
- `end_date` (required): 结束日期，格式 YYYY-MM-DD

**Response** (Success - 200):
```json
{
  "success": true,
  "data": {
    "rentals": [
      {
        "id": 123,
        "ship_out_time": "2025-01-15T10:30:00",
        "customer_name": "用户A",
        "customer_phone": "13800138000",
        "destination": "北京市朝阳区...",
        "device": {
          "id": 45,
          "name": "X200U-001",
          "serial_number": "SN123456",
          "device_model": {
            "name": "Insta360 X200U"
          }
        },
        "accessories": [...]
        // ... 其他字段
      }
    ],
    "count": 10,
    "date_range": {
      "start": "2025-01-01",
      "end": "2025-01-31"
    }
  }
}
```

**Response** (Error - 400):
```json
{
  "success": false,
  "message": "Invalid date range"
}
```

**Query Logic**:
```python
rentals = Rental.query.filter(
    Rental.ship_out_time >= start_date,
    Rental.ship_out_time < end_date + timedelta(days=1),
    Rental.status != 'cancelled'
).order_by(Rental.ship_out_time.asc()).all()
```

## Print Styling Strategy

### CSS Media Query for Print

```css
/* 打印时的样式 */
@media print {
  /* 隐藏非打印元素 */
  .print-hide, .action-bar, .el-button {
    display: none !important;
  }

  /* 每个发货单独立成页 */
  .shipping-order-page-wrapper {
    page-break-after: always;
    page-break-inside: avoid;
  }

  /* 最后一个发货单不分页 */
  .shipping-order-page-wrapper:last-child {
    page-break-after: auto;
  }

  /* 打印纸张设置 */
  @page {
    size: A4;
    margin: 10mm;
  }

  /* 确保表格不被截断 */
  table {
    page-break-inside: avoid;
  }
}
```

### Component Reuse Strategy

为避免重复代码，将 `ShippingOrderView.vue` 的核心内容提取为独立组件：

```vue
<!-- ShippingOrderContent.vue (新建) -->
<template>
  <div class="shipping-order-container">
    <!-- 发货单内容，从 ShippingOrderView.vue 提取 -->
  </div>
</template>

<script setup>
defineProps<{ rental: Rental }>()
</script>
```

然后在两处复用：
1. `ShippingOrderView.vue` (单个打印)
2. `BatchShippingOrderView.vue` (批量打印)

## Data Validation

### Validation Service

```python
# app/services/rental/print_validation_service.py

class PrintValidationService:
    @staticmethod
    def validate_rental_for_print(rental: Rental) -> dict:
        """
        验证租赁记录是否适合打印

        Returns:
            {
                'valid': bool,
                'warnings': list[str],
                'errors': list[str]
            }
        """
        warnings = []
        errors = []

        # 必填字段检查
        if not rental.customer_name:
            errors.append('缺少客户姓名')
        if not rental.customer_phone:
            warnings.append('缺少客户电话')
        if not rental.destination:
            errors.append('缺少收货地址')
        if not rental.device:
            errors.append('缺少设备信息')
        if not rental.ship_out_time:
            warnings.append('缺少寄出时间')

        return {
            'valid': len(errors) == 0,
            'warnings': warnings,
            'errors': errors
        }
```

### Frontend Validation Display

在 `BatchShippingOrderView` 中显示验证警告：

```vue
<el-alert
  v-if="validationWarnings.length > 0"
  type="warning"
  :closable="false"
  class="print-hide"
>
  <template #title>
    以下订单存在数据缺失，可能影响打印质量：
  </template>
  <ul>
    <li v-for="warning in validationWarnings" :key="warning.rentalId">
      订单 #{{ warning.rentalId }}: {{ warning.issues.join(', ') }}
    </li>
  </ul>
</el-alert>
```

## Error Handling

### Scenarios & Solutions

1. **日期范围无订单**
   - 在对话框预览时提示"该日期范围内无待发货订单"
   - 禁用"开始打印"按钮

2. **API 请求失败**
   - 显示错误消息："加载订单失败，请检查网络连接"
   - 提供"重试"按钮

3. **部分订单数据缺失**
   - 显示警告但允许继续打印
   - 缺失字段显示为"-"或占位符

4. **打印过程中断**
   - 用户可关闭打印对话框后重新触发
   - 不影响数据状态

## Performance Considerations

### Loading Optimization

- **懒加载设备图片**：使用 `loading="lazy"` 属性
- **限制单次查询数量**：建议最多 50 条，超过时分批打印
- **虚拟滚动（可选）**：如果订单数超过 20 条，考虑虚拟列表

### Print Performance

- **分页打印**：每个发货单独立页面，避免浏览器内存溢出
- **简化打印内容**：移除不必要的动画、阴影效果
- **测试阈值**：在实际环境测试 10/20/30 条订单的打印表现

## Browser Compatibility

- **目标浏览器**：Chrome 最新版 (Mac)
- **打印API**：`window.print()` - 所有现代浏览器支持
- **CSS Grid/Flexbox**：发货单布局使用 Grid，Chrome 支持良好
- **分页控制**：`page-break-after` - Chrome 支持

## Future Enhancements (Not in MVP)

1. **打印预览模式**：在页面内嵌入预览，无需打开打印对话框
2. **自定义订单选择**：允许用户勾选/取消特定订单
3. **打印模板配置**：支持自定义发货单样式
4. **打印历史记录**：记录每次批量打印的日期和订单数
5. **导出 PDF**：生成 PDF 文件供离线保存

## Security Considerations

- **日期范围验证**：防止恶意查询（如 100 年跨度）
- **权限控制**：批量打印功能应限制给有权限的用户
- **数据脱敏**：打印内容不应包含敏感的内部备注

## Deployment Notes

- 无需数据库迁移
- 无需新增环境变量
- 前端需要重新构建并部署静态资源
- 后端需要重启 Flask 应用加载新路由
