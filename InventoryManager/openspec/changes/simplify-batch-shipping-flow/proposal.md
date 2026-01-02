# 简化批量发货流程 - 自动获取运单号

## Why

当前批量发货流程（enhance-batch-shipping-workflow）需要手动扫描运单号，存在以下问题：

1. **效率低下**：需要先打印发货单，然后手动扫描顺丰面单录入运单号，最后才能预约发货
2. **依赖硬件**：需要扫码枪等硬件设备
3. **流程复杂**：需要经过"打印发货单 → 扫描发货单二维码 → 扫描顺丰面单 → 录入运单号"多个步骤
4. **容易出错**：手动扫描可能扫错或遗漏

实际上，顺丰API已经支持在下单时**自动生成运单号**（通过设置 `isGenWaybillNo=1`），下单成功后会在响应的 `apiResultData.waybillNoInfoList` 中返回运单号。这意味着我们可以在预约发货时直接调用顺丰API下单并获取运单号，无需手动扫描。

## What Changes

### 核心改变

**移除运单号扫描步骤**，改为在预约发货时自动获取运单号：

1. **预约发货时直接下单**：
   - 用户选择待发货订单，设置预约时间
   - 点击"预约发货"后，立即调用顺丰API下单（已在之前的修改中实现）
   - 顺丰API返回自动生成的运单号

2. **自动保存运单号**：
   - 从API响应的 `apiResultData.waybillNoInfoList[0].waybillNo` 提取运单号
   - 保存到 `rental.ship_out_tracking_no` 字段

3. **删除扫描相关功能**：
   - 删除 `/record-waybill` API端点（手动录入运单号）
   - 删除 `/scan-rental` API端点（扫描发货单二维码）
   - 移除前端的扫码监听和弹窗逻辑
   - 移除发货单模板上的二维码

### 顺丰API参数调整

修改 `place_shipping_order` 方法中的参数：

**之前（需要预先提供运单号）**：
```python
'waybillNoInfoList': [{'waybillType': 1, 'waybillNo': rental.ship_out_tracking_no}],
'isGenWaybillNo': 0,
'isUnifiedWaybillNo': 1
```

**现在（让顺丰自动生成运单号）**：
```python
'waybillNoInfoList': [{'waybillType': 1}],
'isGenWaybillNo': 1,  # 改为1，自动生成运单号
'isUnifiedWaybillNo': 1
```

### 响应处理

从顺丰API响应中提取运单号：

```python
# API响应结构（成功时）
{
  'apiResultCode': 'A1000',
  'apiResultData': '{
    "success": true,
    "waybillNoInfoList": [
      {
        "waybillType": 1,
        "waybillNo": "SF1234567890"  # 自动生成的运单号
      }
    ]
  }'
}
```

## Impact

### 受影响的规格

- **batch-shipping** (修改): 批量发货流程简化，移除扫码步骤
- **shipping-order-scan** (删除): 不再需要扫码录入功能
- **sf-express-integration** (修改): 调整下单参数和响应处理

### 受影响的代码

**删除**：
- `app/routes/shipping_batch_api.py` 中的 `scan_rental()` 和 `record_waybill()` 端点
- `frontend/src/views/BatchShippingView.vue` 中的扫码监听和弹窗逻辑
- `templates/shipping_order2.html` 中的二维码部分

**修改**：
- `app/services/shipping/sf_express_service.py`:
  - `place_shipping_order()`: 修改 `isGenWaybillNo` 参数
  - `create_order()`: 解析响应，提取并返回运单号
- `app/routes/shipping_batch_api.py`:
  - `schedule_shipment()`: 从顺丰API响应中获取运单号，保存到 `rental.ship_out_tracking_no`

### 用户体验改进

- ✅ **更简单**：只需选择订单和设置时间，点击预约发货即可
- ✅ **更快速**：省去手动扫描运单号的步骤
- ✅ **更可靠**：避免手动扫描可能出现的错误
- ✅ **无需硬件**：不依赖扫码枪等硬件设备

### 向后兼容性

**BREAKING CHANGE**：
- 已经手动录入运单号的旧订单不受影响
- 新的预约发货流程不再支持手动录入运单号
- 需要删除扫码相关的UI和API

## Alternatives Considered

### 方案1: 保留手动扫描作为备选
- **优点**: 当顺丰API生成运单号失败时，可以手动补录
- **缺点**: 增加代码复杂度，维护两套流程
- **结论**: 未采用。如果API失败，整个下单流程就失败，不应该进入后续步骤

### 方案2: 先生成运单号，后续再下单
- **优点**: 可以提前获取运单号打印面单
- **缺点**: 需要两次API调用，且可能导致运单号浪费（生成了但未使用）
- **结论**: 未采用。当前方案在预约时下单更符合业务流程

## Dependencies

- 依赖顺丰API支持自动生成运单号功能（`isGenWaybillNo=1`）
- 依赖之前修改中实现的"预约时立即下单"功能
- 需要确保顺丰API响应中包含 `waybillNoInfoList` 字段

## Rollout Plan

### Phase 1: 后端实现（优先级：高）
1. 修改 `sf_express_service.py` 中的顺丰API下单参数
2. 实现响应解析，提取 `waybillNoInfoList` 中的运单号
3. 修改 `schedule_shipment()` API，保存返回的运单号到 `rental.ship_out_tracking_no`

### Phase 2: 清理旧代码（优先级：高）
1. 删除 `scan_rental()` 和 `record_waybill()` API端点
2. 删除前端扫码相关逻辑
3. 删除发货单模板上的二维码

### Phase 3: 测试验证（优先级：高）
1. 测试顺丰API自动生成运单号功能
2. 验证运单号正确保存到数据库
3. 端到端测试完整的预约发货流程

### 测试策略
- **单元测试**: 测试响应解析逻辑，确保正确提取 `waybillNoInfoList`
- **集成测试**: 测试完整的预约发货流程，验证运单号保存
- **边界测试**: 测试API返回格式异常、运单号为空等边界情况
