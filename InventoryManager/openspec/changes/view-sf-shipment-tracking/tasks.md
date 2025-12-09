# Tasks

## Backend API Development

- [x] **创建顺丰物流追踪 API Blueprint**
  - 在 `app/routes/` 下创建 `sf_tracking_api.py`
  - 定义 Blueprint `sf_tracking`,URL 前缀 `/api/sf-tracking`
  - 在 `app/__init__.py` 中注册该 Blueprint
  - 验证:访问 `/api/sf-tracking/` 返回404但不报错

- [x] **实现租赁订单列表 API**
  - 路由:`GET /api/sf-tracking/list`
  - 查询所有 `ship_out_tracking_no IS NOT NULL` 的租赁记录
  - 支持查询参数:`start_date`, `end_date` (基于 `ship_out_time`)
  - 返回字段:rental_id, customer_name, customer_phone, destination, device_name, ship_out_tracking_no, ship_out_time, status
  - 按 `ship_out_time DESC` 排序
  - 默认显示过去4天+未来4天
  - 验证:使用 Postman 测试查询,确认返回正确的租赁列表

- [x] **实现单个运单物流查询 API**
  - 路由:`POST /api/sf-tracking/query`
  - 请求参数:`tracking_number`
  - 使用寄件人手机号后四位 `4947`
  - 调用 `SFExpressSDK.search_routes(tracking_number, check_phone_no)`
  - 调用 `SFExpressSDK.parse_route_response(response)` 解析路由
  - 返回解析后的路由信息:status, routes[], last_update, delivered_time
  - 添加错误处理:API调用失败、单号不存在、手机号验证失败
  - 验证:使用真实运单号测试,确认返回物流轨迹

- [x] **实现批量运单物流查询 API**
  - 路由:`POST /api/sf-tracking/batch-query`
  - 请求参数:`tracking_numbers[]`(运单号列表)
  - 限制:最多100个运单号(顺丰API限制)
  - 调用 `SFExpressSDK.batch_search_routes(tracking_numbers, check_phone_no)`
  - 解析每个运单的路由信息
  - 返回字典:{ tracking_number: route_info }
  - 添加部分失败处理:某些单号查询失败不影响其他单号
  - 验证:批量查询3-5个运单号,确认全部返回结果

- [x] **添加 API 错误处理和日志**
  - 统一错误响应格式:`{ success: false, message: "错误信息" }`
  - 添加 logger.info 记录关键操作(查询运单、API调用)
  - 添加 logger.error 记录异常和失败
  - 处理顺丰API超时、网络错误、认证失败等场景
  - 验证:模拟各种错误场景,确认返回友好错误信息

## Frontend Page Development

- [x] **创建物流追踪 Vue 组件**
  - 在 `frontend/src/views/` 下创建 `SFTrackingView.vue`
  - 定义组件基本结构:页面标题、订单列表区、筛选区
  - 添加到 Vue Router 配置:`/sf-tracking`
  - 验证:访问 `/sf-tracking` 显示页面骨架

- [x] **实现订单列表表格**
  - 使用原生 HTML Table 组件
  - 表格列:租赁ID、客户姓名、客户电话、目的地、设备、运单号、发货时间、物流状态、操作
  - 添加"查看轨迹"按钮列
  - 实现分页功能(前端分页,每页20条)
  - 添加加载状态(spinner)
  - 验证:显示租赁列表,数据正确渲染

- [x] **实现日期筛选功能**
  - 添加快捷筛选按钮
  - 默认显示最近8天的订单(过去4天+未来4天)
  - 添加"最近8天"、"最近7天"、"最近30天"、"全部"快捷选项
  - 筛选条件变化时重新请求 API
  - 验证:切换日期范围,列表正确更新

- [x] **实现物流轨迹详情展示**
  - 创建模态框展示物流轨迹
  - 点击"查看轨迹"按钮,调用查询 API
  - 使用时间轴展示物流节点
  - 显示:操作时间、操作地点、操作备注
  - 显示当前物流状态徽章(揽收/运输/派送/签收)
  - 添加加载状态和空状态提示
  - 验证:查看轨迹,显示完整物流信息

- [x] **实现批量刷新功能**
  - 添加"批量刷新物流"按钮
  - 收集当前列表的所有运单号
  - 调用批量查询 API
  - 更新列表中的物流状态列
  - 显示成功/失败统计
  - 验证:批量刷新,状态正确更新

- [x] **添加错误处理和用户提示**
  - API调用失败时显示 alert 提示
  - 空数据状态:显示"暂无发货订单"占位图
  - 查询失败显示错误提示
  - 验证:模拟各种错误,确认用户体验友好

## Navigation Integration

- [x] **在首页导航栏添加入口**
  - 修改 `templates/index.html` 的导航栏
  - 在"租赁管理"后添加"顺丰物流"链接
  - 链接指向 `/sf-tracking`
  - 添加图标 `bi-truck`
  - 验证:首页导航栏显示新链接,点击跳转正确

- [x] **添加 Flask 路由处理**
  - 在 `app/routes/web_pages.py` 添加 `/sf-tracking` 路由
  - 返回 Vue 应用(类似现有的 `/batch-shipping` 路由)
  - 验证:直接访问 `/sf-tracking` 加载 Vue 应用

## Testing & Validation

- [ ] **后端单元测试**
  - 测试租赁列表查询:有运单号 vs 无运单号
  - 测试日期筛选:边界日期、空结果
  - 测试物流查询:成功、失败、超时
  - 测试批量查询:1个、50个、100个运单号
  - Mock 顺丰 SDK 的返回结果
  - 验证:所有测试通过,覆盖率 > 80%

- [ ] **前端单元测试**
  - 测试组件渲染:空数据、有数据
  - 测试筛选逻辑:日期范围变化
  - 测试交互:点击查看轨迹、批量刷新
  - Mock API 响应
  - 验证:关键交互测试通过

- [ ] **集成测试**
  - 测试完整流程:打开页面 -> 查看列表 -> 查看轨迹
  - 测试筛选流程:选择日期 -> 列表更新
  - 测试批量刷新流程
  - 使用测试数据库和Mock顺丰API
  - 验证:端到端流程正常

- [ ] **手动测试**
  - 在测试环境创建3-5个有运单号的租赁订单
  - 打开物流追踪页面,验证列表显示
  - 点击查看轨迹,验证物流信息(可能需要真实运单号)
  - 测试日期筛选、批量刷新
  - 在不同浏览器测试(Chrome, Safari, Firefox)
  - 验证:用户体验流畅,无明显问题

## Documentation

- [ ] **更新 API 文档**
  - 在 `docs/` 下创建或更新 `SF_TRACKING_API.md`
  - 记录新增的3个 API 端点
  - 提供请求/响应示例
  - 说明错误码和错误处理
  - 验证:文档清晰,开发者可理解

- [ ] **更新用户使用指南**
  - 在 `docs/` 更新使用说明
  - 添加"顺丰物流追踪"功能说明
  - 添加截图或操作步骤
  - 说明注意事项(需要运单号、手机号验证等)
  - 验证:非技术用户可理解

## Deployment

- [ ] **前端构建和部署**
  - 运行 `npm run build` 构建前端
  - 确认新页面打包正确
  - 部署到测试环境
  - 验证:测试环境可访问新页面

- [ ] **后端部署**
  - 部署新的 API 路由
  - 确认顺丰SDK配置正确(凭证、环境)
  - 重启服务
  - 验证:API 可访问,返回正确

- [ ] **生产环境验证**
  - 在生产环境测试新功能
  - 验证首页导航链接正常
  - 验证物流查询返回真实数据
  - 监控错误日志和性能
  - 验证:生产环境运行稳定

## Dependencies

- 依赖任务:无(独立功能)
- 可并行任务:
  - 后端 API 开发 与 前端页面开发 可并行
  - 单元测试 可在开发过程中同步进行
