# 任务清单：简化批量发货流程

## Phase 1: 后端实现（优先级：高）

### Task 1.1: 修改顺丰API下单参数
- [x] 修改 `app/services/shipping/sf_express_service.py` 的 `place_shipping_order()` 方法
- [x] 将 `isGenWaybillNo` 从 `0` 改为 `1`
- [x] 修改 `waybillNoInfoList` 为 `[{'waybillType': 1}]`（移除 `waybillNo` 字段）
- [x] 添加日志记录请求参数
- [x] 移除 `ship_out_tracking_no` 的检查（因为运单号将自动生成）
- [x] 更新 `orderId` 生成逻辑使用时间戳而非运单号

**验证**：
- 检查日志，确认请求参数中 `isGenWaybillNo=1`
- 请求不包含预设的运单号

### Task 1.2: 实现响应解析逻辑
- [x] 修改 `app/utils/sf/sf_sdk_wrapper.py` 的 `create_order()` 方法
- [x] 解析 `apiResultData` JSON字符串
- [x] 从 `waybillNoInfoList[0].waybillNo` 提取运单号
- [x] 在返回结果中包含运单号（作为 `waybill_no` 字段）
- [x] 添加异常处理：JSON解析失败、数组为空、运单号缺失
- [x] 处理 waybillNoInfoList 包含多个元素的情况（记录警告，使用第一个）

**验证**：
- 单元测试：模拟各种响应格式，验证解析逻辑
- 边界测试：空数组、多个元素、格式错误

### Task 1.3: 更新预约发货API保存运单号
- [x] 修改 `app/routes/shipping_batch_api.py` 的 `schedule_shipment()` 方法
- [x] 从顺丰API响应中获取运单号
- [x] 保存运单号到 `rental.ship_out_tracking_no`
- [x] 在返回结果中包含运单号信息（每个订单的 result 中包含 `waybill_no`）
- [x] 添加日志记录运单号保存过程
- [x] 移除 `ship_out_tracking_no` 的前置检查
- [x] 更新错误处理，区分下单失败和运单号缺失

**验证**：
- 测试预约发货流程，检查数据库中运单号是否正确保存
- 验证批量发货时每个订单的运单号独立保存

### Task 1.4: 增强错误处理和日志
- [x] 在 `sf_express_service.py` 中添加详细的错误日志
- [x] 记录每次API调用的完整上下文（Rental ID、时间、参数、响应）
- [x] 区分不同类型的错误（网络错误、业务错误、数据格式错误）
- [x] 在 `sf_sdk_wrapper.py` 中添加运单号提取失败的详细日志
- [x] 确保错误信息返回给前端时清晰可理解

**验证**：
- 检查日志输出格式和内容
- 触发各种错误场景，验证错误信息清晰

## Phase 2: 清理旧代码（优先级：高）

### Task 2.1: 删除运单号录入API
- [x] 删除 `app/routes/shipping_batch_api.py` 中的 `record_waybill()` 端点
- [x] 删除相关的导入和依赖（移除 `re` 模块导入）

**验证**：
- 确认API端点不再可访问
- 检查是否有其他代码引用该端点

### Task 2.2: 删除扫描发货单API
- [x] 删除 `app/routes/shipping_batch_api.py` 中的 `scan_rental()` 端点
- [x] 删除相关的导入和依赖

**验证**：
- 确认API端点不再可访问
- 检查是否有其他代码引用该端点

### Task 2.3: 清理前端扫码逻辑
- [x] 在 `frontend/src/views/BatchShippingView.vue` 中删除扫码监听器
- [x] 删除扫码弹窗组件（Rental Detail Dialog）
- [x] 删除语音提示相关代码（`speak` 函数）
- [x] 更新UI，移除"扫描运单"相关按钮和说明
- [x] 移除 scanner state 变量（scanBuffer, scanTimeout, awaitingWaybill, currentRental, rentalDialogVisible）
- [x] 删除扫码处理函数（handleKeyDown, processScan, handleRentalScan, handleWaybillScan）
- [x] 移除 onMounted/onUnmounted lifecycle hooks
- [x] 更新 hasWaybills 和 waybillCount 计算逻辑（移除运单号检查）
- [x] 更新预约发货按钮的文案和逻辑
- [x] 更新订单状态标签（移除"已录入运单"状态）

**验证**：
- 前端不再有扫码相关功能
- UI界面简洁，流程清晰

### Task 2.4: 移除发货单模板二维码
- [x] 检查 `templates/shipping_order2.html`
- [x] 确认无租赁ID二维码需要移除（二维码功能未曾实现）

**验证**：
- 生成发货单，确认无租赁ID二维码
- 打印效果正常

## Phase 3: 测试验证（优先级：高）

**注意**: Phase 3 和 Phase 4 的任务将在后续单独进行，当前实现聚焦于 Phase 1 和 Phase 2 的核心功能。

### Task 3.1: 单元测试
- [ ] 编写 `test_sf_api_waybill_parsing.py`
- [ ] 测试成功场景：正常提取运单号
- [ ] 测试异常场景：JSON解析失败、数组为空、运单号缺失
- [ ] 测试边界场景：多个运单号、格式异常

**验证**：
- 所有测试用例通过
- 代码覆盖率 > 90%

### Task 3.2: 集成测试
- [ ] 在测试环境调用顺丰API下单
- [ ] 验证自动生成的运单号格式正确
- [ ] 验证运单号保存到数据库
- [ ] 测试批量发货，验证每个订单的运单号独立

**验证**：
- 数据库中 `ship_out_tracking_no` 字段有值
- 运单号格式符合顺丰规范（如 `SF` 开头 + 数字）

### Task 3.3: 端到端测试
- [ ] 从批量发货页面选择订单
- [ ] 设置预约时间，点击预约发货
- [ ] 验证顺丰下单成功
- [ ] 验证运单号自动保存
- [ ] 验证订单状态更新为 `shipped`
- [ ] 验证闲鱼发货通知成功（如有）

**验证**：
- 完整流程无错误
- 用户体验流畅

### Task 3.4: 错误场景测试
- [ ] 测试顺丰API返回错误（如地址错误、月结账号无效）
- [ ] 测试网络超时或连接失败
- [ ] 测试响应格式异常
- [ ] 验证错误提示清晰，订单状态不变

**验证**：
- 错误处理正确，不影响其他订单
- 用户能理解错误原因

## Phase 4: 文档和部署（优先级：中）

### Task 4.1: 更新用户文档
- [ ] 更新批量发货操作手册
- [ ] 说明新的简化流程：选择订单 → 设置时间 → 预约发货
- [ ] 移除扫码相关说明

**验证**：
- 文档清晰易懂
- 与实际操作一致

### Task 4.2: 更新API文档
- [ ] 更新 `/schedule` 端点文档，说明返回的运单号信息
- [ ] 标记 `/record-waybill` 和 `/scan-rental` 为已废弃（Deprecated）

**验证**：
- API文档准确完整

### Task 4.3: 部署前检查
- [ ] 检查环境变量配置（顺丰API凭证）
- [ ] 确认 `isGenWaybillNo=1` 不会影响现有下单流程
- [ ] 备份数据库，准备回滚方案

**验证**：
- 配置正确
- 回滚方案可行

### Task 4.4: 灰度发布
- [ ] 先在测试环境验证
- [ ] 小范围生产环境测试（如1-5个订单）
- [ ] 监控日志和错误率
- [ ] 全量发布

**验证**：
- 生产环境运行正常
- 无错误告警

## 依赖关系

- Task 1.1, 1.2, 1.3 必须按顺序完成（后者依赖前者）
- Task 1.4 可与 1.1-1.3 并行
- Task 2.x 必须在 Task 1.x 完成并测试后进行
- Task 3.1 可在 Task 1.2 完成后开始
- Task 3.2-3.4 依赖 Task 1.x 全部完成
- Task 4.x 可与 Task 3.x 并行

## 预估工作量

- Phase 1: 4-6 小时
- Phase 2: 2-3 小时
- Phase 3: 4-6 小时
- Phase 4: 2-3 小时

**总计**: 12-18 小时（约 2-3 个工作日）
