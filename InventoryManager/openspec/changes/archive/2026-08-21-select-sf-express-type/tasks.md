# Tasks

## Database Migration

- [x] **创建数据库迁移脚本**
  - 在 `rentals` 表中增加 `express_type_id` 字段
  - 类型: `INTEGER`
  - 应用默认值: `2`; 初始迁移回填历史 `NULL`,不宣称数据库 `server_default`
  - 添加注释: "顺丰快递类型ID (1=特快,2=标快,263=半日达)"
  - 验证: 迁移脚本可以在测试环境成功执行

- [x] **执行数据库迁移**
  - 在开发环境执行迁移
  - 验证字段已添加: `DESC rentals;`
  - 验证现有记录的默认值: `SELECT id, express_type_id FROM rentals LIMIT 10;`

## Backend Development

- [x] **更新 Rental 模型**
  - 在 `app/models/rental.py` 中增加 `express_type_id` 字段定义
  - 在 `to_dict()` 方法中包含该字段
  - 验证: 模型字段定义正确,不影响现有功能

- [x] **实现快递类型更新 API**
  - 路由: `PATCH /api/shipping-batch/express-type`
  - 请求参数: `rental_id` (int), `express_type_id` (int)
  - 验证 `express_type_id` 在 `[1, 2, 263]` 范围内
  - 查询租赁记录并更新 `express_type_id` 字段
  - 已有运单号或已预约/发货时返回 `409`,锁定产品类型
  - 返回更新结果: `{ success: true, message: "快递类型已更新" }`
  - 错误处理: 租赁记录不存在、参数无效等场景
  - 验证: 使用 Postman 测试 API,确认可以成功更新字段

- [x] **修改顺丰下单服务**
  - 修改 `app/services/shipping/sf_express_service.py` 的 `place_shipping_order()` 方法
  - 从 `rental.express_type_id` 读取快递类型
  - 仅当字段为空时使用默认值 `2` (标快); 非法值 fail closed
  - 将该值赋给 `order_data['expressTypeId']` (替换当前硬编码的 `1`)
  - 半日达同时传递 `specialDeliveryTypeCode=263`
  - 添加日志记录: `logger.info(f"使用快递类型: {express_type_id}")`
  - 验证: 调用下单接口,检查日志确认使用正确的快递类型

## Frontend Development

- [x] **在批量发货页面增加快递类型列**
  - 在 `frontend/src/views/BatchShippingView.vue` 的表格中增加一列
  - 列标题: "快递类型"
  - 列宽: `width="120"`
  - 使用 `el-select` 组件显示三个选项:
    - 值 `1`: 显示 "特快"
    - 值 `2`: 显示 "标快" (默认)
    - 值 `263`: 显示 "半日达"
  - 验证: 表格中显示快递类型选择器

- [x] **实现快递类型选择器交互**
  - 绑定 `v-model` 到 `row.express_type_id`
  - 默认值: `row.express_type_id || 2` (标快)
  - 监听 `@change` 事件,调用 `updateExpressType(row.id, newValue)`
  - 运单号已存在或状态已预约/发货时禁用选择器
  - 验证: 选择不同选项时,触发更新函数

- [x] **实现快递类型更新函数**
  - 定义 `updateExpressType(rentalId: number, expressTypeId: number)` 方法
  - 调用 `PATCH /api/shipping-batch/express-type` API
  - 成功时显示提示: `ElMessage.success('快递类型已更新')`
  - 失败时显示错误: `ElMessage.error('更新失败')`
  - 成功时保存持久值快照,失败时将 UI 回滚到上次持久值
  - 验证: 选择快递类型后,成功调用 API 并显示提示

- [x] **处理加载租赁列表时的快递类型**
  - 确保 `previewOrders()` 方法返回的数据包含 `express_type_id` 字段
  - 如果后端未返回该字段,前端使用默认值 `2`
  - 验证: 加载订单列表时,快递类型选择器显示正确的值

## Testing

- [x] **后端 API 与顺丰服务测试**
  - 测试快递类型更新 API:
    - 成功更新
    - 租赁记录不存在
    - 参数无效 (`6`/`99`/字符串/布尔值)
    - 缺少参数
    - 运单创建后锁定
  - 测试顺丰下单服务:
    - 使用租赁记录的 `express_type_id`
    - 字段为空时使用默认值
    - 半日达同时传 `expressTypeId=263` 和 `specialDeliveryTypeCode=263`
    - 非法存量值不调用 provider
  - 验证: `tests/integration/test_express_type_selection.py` 20 passed

- [x] **前端单元测试**
  - 测试快递类型选择器渲染
  - 测试选择变更时调用 API
  - 测试默认值处理
  - 测试运单后禁用和失败回滚
  - 验证: `BatchShippingView.spec.ts` 13 passed

- [x] **集成测试**
  - 端到端测试完整流程:
    1. 打开批量发货页面
    2. 加载订单列表
    3. 修改某个订单的快递类型
    4. 预约发货
    5. 验证顺丰请求包含正确的产品字段
    6. 验证成功建单后 PATCH 被拒绝
  - 验证: provider 使用 fake 边界,不发起真实第三方副作用; 流程测试通过

- [x] **记录手动与真实账号验证边界**
  - 本 change 的归档不声称执行真实顺丰下单或生产手动验收
  - 真实账号 capability test、测试环境 E2E 和生产验收分别转入 SaaS tasks 0.11、13.2、14.1-14.8
  - 验证: 归档记录保留该边界,不会把 fake-provider 结果描述成真实顺丰验证

## Documentation

- [x] **更新 API 文档**
  - 记录新增的 `PATCH /api/shipping-batch/express-type` 端点
  - 提供请求/响应示例
  - 说明参数验证规则
  - 记录 `409` 锁定响应、263 半日达字段和非法值 fail-closed
  - 验证: 本 change 的 proposal 和 delta spec 已同步

- [x] **记录用户文档交接**
  - proposal/spec 已记录三个选项、应用默认值和运单后锁定
  - 面向用户的最终 SaaS 操作手册随 tasks 13.7/14.1 生成,避免为即将替换的单租户页面制作双份手册

## Rollout Boundary

- [x] **将部署责任转交 SaaS 发布门禁**
  - 未在本次收尾中部署测试或生产环境,也未修改实际数据库
  - 数据盘点/迁移演练/备份恢复/灰度/监控由 SaaS tasks 0.2、12.x、13.x、14.x 执行
  - D12 要求在 SaaS 切换前归档本 change；归档不等同于部署完成声明

## Dependencies
- 依赖任务: 无(独立功能)
- 可并行任务:
  - 后端开发 与 前端开发 可并行
  - 单元测试 可在开发过程中同步进行
