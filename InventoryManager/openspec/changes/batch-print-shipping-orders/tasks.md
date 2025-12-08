# Tasks

## Backend Tasks

- [x] **Task 1: 创建批量查询 API**
  - 在 `app/routes/rental_api.py` 添加 `/api/rentals/by-ship-date` 端点
  - 接受参数：`start_date`, `end_date`
  - 查询条件：`ship_out_time` 在日期范围内，且状态非 `cancelled`
  - 返回完整租赁信息（含设备、附件）
  - 按 `ship_out_time` 升序排序
  - 验证：使用 Postman/curl 测试 API 返回正确数据

- [ ] **Task 2: 添加数据验证服务**
  - 在 `app/services/rental/` 创建 `print_validation_service.py`
  - 实现 `validate_rental_for_print()` 方法
  - 检查必填字段：客户信息、设备信息、地址
  - 返回验证结果和缺失字段列表
  - 验证：单元测试覆盖各种数据缺失场景
  - 注：此任务可选，暂时跳过，MVP不需要

## Frontend Tasks

- [x] **Task 3: 创建批量打印对话框组件**
  - 在 `frontend/src/components/` 创建 `BatchPrintDialog.vue`
  - 实现日期范围选择器（开始日期、结束日期）
  - 添加"预览订单"按钮，显示将要打印的订单列表
  - 添加"开始打印"按钮，跳转到批量打印视图
  - 错误处理：日期范围无效、无订单提示
  - 验证：在甘特图页面手动测试对话框交互

- [x] **Task 4: 在甘特图添加批量打印按钮**
  - 在 `frontend/src/components/GanttChart.vue` 添加顶部工具栏按钮
  - 按钮文本：📦 批量打印发货单
  - 点击打开 `BatchPrintDialog` 对话框
  - 按钮位置：与其他操作按钮对齐
  - 验证：确认按钮显示正确，点击弹出对话框

- [x] **Task 5: 创建批量打印视图页面**
  - 在 `frontend/src/views/` 创建 `BatchShippingOrderView.vue`
  - 路由路径：`/batch-shipping-order`
  - 接受 URL 参数：`start_date`, `end_date`
  - 调用批量查询 API 获取租赁记录
  - 遍历渲染多个发货单（复用 `ShippingOrderView` 的模板结构）
  - 添加加载状态和错误处理
  - 验证：手动访问路由，确认能加载多条记录

- [x] **Task 6: 实现打印分页样式**
  - 在 `BatchShippingOrderView.vue` 添加 `@media print` 样式
  - 每个发货单设置 `page-break-after: always`
  - 隐藏打印时不需要的元素（按钮、导航栏）
  - 确保每张发货单独立成页
  - 验证：Chrome 打印预览查看分页效果

- [x] **Task 7: 添加批量打印功能**
  - 在 `BatchShippingOrderView.vue` 添加顶部操作栏
  - "返回甘特图"按钮
  - "打印所有发货单"按钮（调用 `window.print()`）
  - 显示当前加载的订单数量
  - 打印前检查数据完整性，显示警告信息
  - 验证：测试打印 1/3/5 个订单，确认顺序和内容正确

- [x] **Task 8: 优化加载体验**
  - 添加骨架屏或加载动画
  - 批量加载时显示进度（已加载 X/Y 条）
  - 数据加载失败时友好提示并允许重试
  - 验证：模拟慢网络测试加载体验

## Testing Tasks

- [ ] **Task 9: 集成测试**
  - 测试空日期范围（无订单）
  - 测试有效日期范围（1/5/10 条订单）
  - 测试跨月日期范围
  - 测试包含不完整数据的订单
  - 验证：所有测试场景通过

- [ ] **Task 10: 打印测试**
  - 使用实际网络打印机测试打印
  - 验证分页正确（每个订单独立页）
  - 验证打印顺序与发货时间一致
  - 验证中文字符和布局正确
  - 测试批量打印 20+ 订单的性能
  - 验证：打印输出符合预期

## Documentation Tasks

- [ ] **Task 11: 更新用户文档**
  - 在 README 或用户手册添加批量打印说明
  - 包含操作步骤截图
  - 说明常见问题和解决方案
  - 验证：用户可按文档完成操作

## Dependencies

- Task 3 依赖 Task 1（需要 API 支持）
- Task 5 依赖 Task 1（需要 API 数据）
- Task 7 依赖 Task 5 和 Task 6（需要页面和样式就绪）
- Task 9 依赖 Task 1-8（需要功能完整）
- Task 10 依赖 Task 7（需要打印功能就绪）

## Parallelizable Work

- Task 1-2 (后端) 和 Task 3-4 (前端对话框) 可并行开发
- Task 5-6 (批量视图) 可在 Task 1 完成后开始
- Task 8 (优化) 可在基础功能完成后并行进行
