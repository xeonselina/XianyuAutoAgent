# Tasks

## Database Migration

- [x] **创建数据库迁移脚本**
  - 在 `rentals` 表中增加 `express_type_id` 字段
  - 类型: `INTEGER`
  - 默认值: `2`
  - 添加注释: "顺丰快递类型ID (1=特快,2=标快,6=半日达)"
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
  - 验证 `express_type_id` 在 `[1, 2, 6]` 范围内
  - 查询租赁记录并更新 `express_type_id` 字段
  - 返回更新结果: `{ success: true, message: "快递类型已更新" }`
  - 错误处理: 租赁记录不存在、参数无效等场景
  - 验证: 使用 Postman 测试 API,确认可以成功更新字段

- [x] **修改顺丰下单服务**
  - 修改 `app/services/shipping/sf_express_service.py` 的 `place_shipping_order()` 方法
  - 从 `rental.express_type_id` 读取快递类型
  - 如果字段为空或无效,使用默认值 `2` (标快)
  - 将该值赋给 `order_data['expressTypeId']` (替换当前硬编码的 `1`)
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
    - 值 `6`: 显示 "半日达"
  - 验证: 表格中显示快递类型选择器

- [x] **实现快递类型选择器交互**
  - 绑定 `v-model` 到 `row.express_type_id`
  - 默认值: `row.express_type_id || 2` (标快)
  - 监听 `@change` 事件,调用 `updateExpressType(row.id, newValue)`
  - 验证: 选择不同选项时,触发更新函数

- [x] **实现快递类型更新函数**
  - 定义 `updateExpressType(rentalId: number, expressTypeId: number)` 方法
  - 调用 `PATCH /api/shipping-batch/express-type` API
  - 成功时显示提示: `ElMessage.success('快递类型已更新')`
  - 失败时显示错误: `ElMessage.error('更新失败')`
  - 更新 `rentals` 数组中对应记录的 `express_type_id`
  - 验证: 选择快递类型后,成功调用 API 并显示提示

- [x] **处理加载租赁列表时的快递类型**
  - 确保 `previewOrders()` 方法返回的数据包含 `express_type_id` 字段
  - 如果后端未返回该字段,前端使用默认值 `2`
  - 验证: 加载订单列表时,快递类型选择器显示正确的值

## Testing

- [ ] **后端单元测试**
  - 测试快递类型更新 API:
    - 成功更新
    - 租赁记录不存在
    - 参数无效 (expressTypeId=99)
    - 缺少参数
  - 测试顺丰下单服务:
    - 使用租赁记录的 `express_type_id`
    - 字段为空时使用默认值
  - 验证: 所有测试通过

- [ ] **前端单元测试**
  - 测试快递类型选择器渲染
  - 测试选择变更时调用 API
  - 测试默认值处理
  - 验证: 测试通过

- [ ] **集成测试**
  - 端到端测试完整流程:
    1. 打开批量发货页面
    2. 加载订单列表
    3. 修改某个订单的快递类型
    4. 预约发货
    5. 验证顺丰API接收到正确的 `expressTypeId`
  - 验证: 完整流程正常工作

- [ ] **手动测试**
  - 在测试环境创建3-5个租赁订单
  - 打开批量发货页面,验证"快递类型"列显示
  - 为不同订单选择不同的快递类型
  - 预约发货,检查日志确认使用正确的快递类型
  - 测试边界情况:
    - 新创建的订单(无 express_type_id)
    - 已发货的订单
  - 验证: 用户体验流畅,功能正常

## Documentation

- [ ] **更新 API 文档**
  - 记录新增的 `PATCH /api/shipping-batch/express-type` 端点
  - 提供请求/响应示例
  - 说明参数验证规则
  - 验证: 文档清晰完整

- [ ] **更新用户手册**
  - 在批量发货功能说明中增加快递类型选择说明
  - 解释三种快递类型的差异(时效、价格)
  - 说明默认值和推荐选择
  - 验证: 用户可理解

## Deployment

- [ ] **部署到测试环境**
  - 执行数据库迁移
  - 部署后端代码
  - 构建并部署前端代码
  - 验证: 测试环境功能正常

- [ ] **部署到生产环境**
  - 执行数据库迁移(带备份)
  - 部署后端代码
  - 部署前端代码
  - 监控错误日志
  - 验证: 生产环境运行稳定

## Dependencies
- 依赖任务: 无(独立功能)
- 可并行任务:
  - 后端开发 与 前端开发 可并行
  - 单元测试 可在开发过程中同步进行
