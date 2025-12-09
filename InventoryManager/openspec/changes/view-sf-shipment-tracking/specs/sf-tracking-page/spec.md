# 顺丰物流追踪页面规范

此规范定义了顺丰物流追踪页面的需求,允许用户查看和追踪通过批量发货流程创建的快递单。

## ADDED Requirements

### Requirement: 显示已发货租赁列表

系统 SHALL 提供一个页面,显示所有已录入顺丰运单号的租赁记录。

#### Scenario: 用户查看发货列表

**Given** 存在 `ship_out_tracking_no` 字段已填充的租赁记录
**When** 用户访问 `/sf-tracking` 页面
**Then** 系统显示包含以下列的表格:租赁ID、客户姓名、客户电话、目的地、设备名称、运单号、发货时间、操作
**And** 租赁记录按 `ship_out_time` 降序排列(最新的在前)

#### Scenario: 用户查看空列表

**Given** 没有租赁记录有运单号
**When** 用户访问 `/sf-tracking` 页面
**Then** 系统显示空状态提示 "暂无发货订单"

### Requirement: 按日期范围筛选发货记录

系统 SHALL 允许按发货日期范围筛选发货记录。

#### Scenario: 用户按日期范围筛选

**Given** 用户在顺丰物流追踪页面
**When** 用户在日期选择器中选择开始日期和结束日期
**Then** 系统查询 `ship_out_time` 在选定日期之间的租赁记录
**And** 更新表格仅显示匹配的租赁记录

#### Scenario: 用户选择快捷筛选预设

**Given** 用户在顺丰物流追踪页面
**When** 用户点击 "最近7天" 快捷筛选
**Then** 系统筛选显示最近7天的租赁记录
**When** 用户点击 "最近30天" 快捷筛选
**Then** 系统筛选显示最近30天的租赁记录
**When** 用户点击 "全部" 快捷筛选
**Then** 系统移除日期筛选,显示所有租赁记录

### Requirement: 查询单个运单物流轨迹

系统 SHALL 提供 API 查询单个运单号的物流信息。

#### Scenario: 用户查看发货单的物流详情

**Given** 某租赁记录的运单号为 "SF1234567890",客户电话为 "13800138000"
**When** 用户点击该租赁记录的 "查看轨迹" 按钮
**Then** 系统调用 `POST /api/sf-tracking/query`,传入 `tracking_number` 和 `check_phone_no`(后4位)
**And** 调用顺丰 SDK 的 `search_routes(tracking_number, check_phone_no)` 方法
**And** 显示物流轨迹时间轴,包含每个节点的操作时间、操作地点、操作备注
**And** 显示当前物流状态徽章(揽收/运输中/派送中/已签收)

#### Scenario: 物流查询失败

**Given** 用户点击某租赁记录的 "查看轨迹"
**When** 顺丰 API 返回错误或超时
**Then** 系统显示错误消息 "查询物流信息失败,请稍后重试"
**And** 记录错误日志,包含运单号和错误详情

### Requirement: 批量查询运单物流轨迹

系统 SHALL 提供 API 在一次请求中查询多个运单的物流信息。

#### Scenario: 用户批量刷新物流状态

**Given** 物流追踪列表中显示了5条租赁记录
**When** 用户点击 "批量刷新物流" 按钮
**Then** 系统收集列表中所有租赁记录的运单号
**And** 调用 `POST /api/sf-tracking/batch-query`,传入运单号数组
**And** 调用顺丰 SDK 的 `batch_search_routes(tracking_numbers, check_phone_no)` 方法
**And** 显示进度提示 "查询中 X/5"
**And** 更新每条租赁记录的最新物流状态

#### Scenario: 批量查询超出限制

**Given** 用户尝试批量查询150个运单号
**When** 发送请求
**Then** 系统返回错误 "一次最多查询100个运单号"(顺丰 API 限制)

### Requirement: 从首页导航访问

系统 SHALL 在主页提供导航入口访问顺丰物流追踪页面。

#### Scenario: 用户从首页导航到物流追踪页面

**Given** 用户在首页
**When** 用户查看导航栏
**Then** 系统在 "租赁管理" 之后显示 "顺丰物流" 链接
**When** 用户点击 "顺丰物流" 链接
**Then** 系统导航到 `/sf-tracking` 页面

## ADDED API Endpoints

### Requirement: 租赁列表 API 端点

系统 SHALL 提供 API 端点检索有运单号的租赁记录。

#### Scenario: 查询所有有运单号的租赁记录

**Given** API 接收到 `GET /api/sf-tracking/list` 请求
**When** 未提供查询参数
**Then** 系统查询 `Rental` 表中 `ship_out_tracking_no IS NOT NULL` 的记录
**And** 返回 JSON 数组,包含 rental_id, customer_name, customer_phone, destination, device_name, ship_out_tracking_no, ship_out_time, status

#### Scenario: 按日期范围查询租赁记录

**Given** API 接收到 `GET /api/sf-tracking/list?start_date=2024-01-01&end_date=2024-01-31` 请求
**When** 处理请求
**Then** 系统查询 `Rental` 表中 `ship_out_tracking_no IS NOT NULL` 且 `ship_out_time` 在 start_date 和 end_date 之间的记录
**And** 返回筛选后的租赁列表

### Requirement: 单个运单查询 API

系统 SHALL 提供 API 端点查询单个运单的物流信息。

#### Scenario: 使用有效参数查询物流

**Given** API 接收到 `POST /api/sf-tracking/query`,请求体为 `{ "tracking_number": "SF1234567890", "check_phone_no": "8000" }`
**When** 处理请求
**Then** 系统调用 `SFExpressSDK.search_routes("SF1234567890", "8000")`
**And** 调用 `SFExpressSDK.parse_route_response(response)`
**And** 返回 JSON,包含 status, routes 数组, last_update, delivered_time

#### Scenario: 缺少必要参数查询物流

**Given** API 接收到 `POST /api/sf-tracking/query`,请求体为空
**When** 处理请求
**Then** 系统返回 HTTP 400,错误消息为 "缺少必要参数"

### Requirement: 批量运单查询 API

系统 SHALL 提供 API 端点查询多个运单的物流信息。

#### Scenario: 使用有效运单号批量查询

**Given** API 接收到 `POST /api/sf-tracking/batch-query`,请求体为 `{ "tracking_numbers": ["SF001", "SF002"], "check_phone_no": "8000" }`
**When** 处理请求
**Then** 系统调用 `SFExpressSDK.batch_search_routes(["SF001", "SF002"], "8000")`
**And** 解析每个运单的路由响应
**And** 返回 JSON 对象,将 tracking_number 映射到 route_info

#### Scenario: 批量查询超出数量限制

**Given** API 接收到 `POST /api/sf-tracking/batch-query`,包含150个运单号
**When** 处理请求
**Then** 系统返回 HTTP 400,错误消息为 "一次最多查询100个运单号"
