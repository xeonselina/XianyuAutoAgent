# 增强批量发货工作流

## Why

当前批量打印发货单功能(batch-print-shipping-orders)只能批量打印,但整个发货流程仍需手动操作:
1. 打印发货单后,需要手动逐个扫描顺丰面单录入运单号
2. 无法追踪哪些发货单已打印、已扫描、已发货
3. 需要手动调用顺丰API下单和闲鱼API发货通知
4. 容易遗漏或重复操作,无统一的批量发货会话管理

本变更将批量打印升级为完整的批量发货工作流,通过扫码枪、二维码识别、定时任务等技术,实现:
- 批量打印 → 扫码录入 → 预约发货 → 自动调用API 的端到端自动化
- 提升发货效率,减少人工错误,提供清晰的发货进度追踪

## What Changes

### 用户体验改进
1. **重命名按钮**: 将"批量打印发货单"改名为"批量发货"
2. **新批量发货页面**: 点击"批量发货"打开独立页面(非对话框)
   - 日期范围选择器
   - "预览订单"按钮加载待发货订单列表
   - 订单列表显示基本信息和状态(未打印/已打印/已录入运单/已发货)
3. **发货单二维码**: 每张发货单右上角显示rental ID的二维码
4. **扫码录入工作流**:
   - 扫描发货单二维码 → 弹框显示租赁详情(地址、电话、设备、附件、时间)
   - 语音提示"请扫描顺丰面单"
   - 扫描顺丰面单 → 录入运单号到数据库
   - 自动关闭弹框,继续扫描下一单
5. **预约发货功能**:
   - "预约发货"按钮,弹框输入发货时间(默认1小时后)
   - 显示将被预约的订单数量(仅已录入运单的订单)
6. **定时发货执行**:
   - 到达预约时间后,后台任务自动执行:
     - 调用顺丰速运API下单
     - 调用闲鱼管家API发货通知
     - 更新rental状态为'shipped'

### 技术实现
- **数据模型**: Rental表新增字段 `scheduled_ship_time`, `sf_waybill_no`
- **发货单模板**: 在右上角添加二维码(基于rental ID)
- **批量发货页面**: 新Vue页面 `BatchShippingView.vue`,包含订单列表、扫码、预约功能
- **扫码处理**: 前端监听扫码枪输入,识别二维码(rental ID)和顺丰面单号(正则匹配)
- **语音提示**: 使用Web Speech API播放语音提示
- **API端点**:
  - `POST /api/shipping-batch/scan-rental` - 扫描rental二维码
  - `POST /api/shipping-batch/record-waybill` - 录入运单号
  - `POST /api/shipping-batch/schedule` - 预约发货
- **顺丰速运集成**: 参考 `docs/速运API.docx` 和 `docs/顺丰oauth2鉴权.docx`
- **闲鱼管家集成**: 参考 `docs/闲鱼管家 api 文档.md` 的发货接口
- **定时任务**: 使用APScheduler定期检查 `scheduled_ship_time`,执行发货API调用

## Impact

### 受影响的规格(Affected Specs)
- **batch-shipping** (新): 批量发货会话管理
- **shipping-order-scan** (新): 发货单扫码录入
- **sf-express-integration** (新): 顺丰速运API集成
- **xianyu-api-integration** (新): 闲鱼管家API集成

### 受影响的代码
- `frontend/src/components/GanttChart.vue` - 按钮文本修改
- `frontend/src/views/BatchShippingOrderView.vue` - 发货单二维码
- `frontend/src/views/BatchShippingView.vue` - 新批量发货页面(替代原对话框)
- `app/models/rental.py` - 新增字段
- `app/routes/shipping_batch_api.py` - 新API路由
- `app/services/shipping/` - 新服务模块
- `app/utils/scheduler_tasks.py` - 定时发货任务
- `templates/shipping_order2.html` - 发货单模板(添加二维码)

### 数据库变更
- **BREAKING**: 需要数据库迁移,新增字段:
  - `rentals.scheduled_ship_time` (DateTime, nullable)
  - `rentals.sf_waybill_no` (String, nullable) - 顺丰运单号(区别于ship_out_tracking_no)

### 用户影响
- **效率提升**: 扫码录入比手动输入快5-10倍
- **减少错误**: 自动调用API,避免遗漏发货通知
- **透明度**: 清晰的发货进度追踪

### 系统影响
- **外部依赖**: 依赖顺丰API和闲鱼API的可用性和正确配置
- **定时任务**: 需要APScheduler正常运行
- **扫码枪**: 需要USB扫码枪硬件支持

### 风险评估
- **API失败**: 顺丰/闲鱼API调用失败时需要重试机制和人工介入
- **扫码错误**: 误扫或扫错需要撤销/修正功能
- **定时任务**: 服务器重启可能导致scheduled任务丢失(需要持久化)

## Alternatives Considered

### 方案1: 使用WebSocket实时推送扫码结果
- **优点**: 实时性更好,多人协作扫码
- **缺点**: 增加复杂度,当前单人操作不需要
- **结论**: 未选择,优先简单的轮询或事件驱动方案

### 方案2: 使用独立的ShippingBatch表管理批量发货会话
- **优点**: 更清晰的批次管理,历史记录
- **缺点**: 增加数据模型复杂度
- **结论**: 未选择,Phase 1使用rental字段即可,后续可扩展

### 方案3: 立即调用API而非定时调用
- **优点**: 更简单,无需定时任务
- **缺点**: 无法批量操作,失去预约发货的业务价值(集中在特定时间发货)
- **结论**: 未选择,保留预约发货功能

## Dependencies

- 依赖 `batch-print-shipping-orders` 变更的批量打印基础功能
- 依赖 `app/utils/sf_express_api.py` 的路由查询功能(需扩展下单功能)
- 依赖顺丰API和闲鱼管家API的凭证配置(需在环境变量中配置)
- 依赖APScheduler或Celery等定时任务框架

## Rollout Plan

### Phase 1: 核心发货流程(MVP)
1. 数据库迁移: 新增字段
2. 发货单二维码: 模板修改
3. 批量发货页面: 日期选择、订单列表、扫码录入
4. API端点: 扫码、录入运单、预约发货
5. 定时任务: 检查scheduled_ship_time并执行发货

### Phase 2: API集成
1. 顺丰速运API: OAuth2鉴权、下单接口
2. 闲鱼管家API: 签名鉴权、发货通知接口
3. 错误处理和重试机制

### Phase 3: 优化增强
1. 撤销/修正扫码错误
2. 发货历史和统计报表
3. 批量发货会话管理(ShippingBatch表)
4. 语音提示优化(支持不同状态的语音反馈)

### 测试策略
- 单元测试: 扫码解析、API签名生成、定时任务触发
- 集成测试: 完整发货流程端到端测试
- 手动测试: 实际扫码枪测试、API调用测试
- 边界测试: 重复扫码、API失败、定时任务异常
