# 规格: 闲鱼API集成

## ADDED Requirements

### Requirement: Xianyu Order Detail API Client Service

The system MUST provide a service class to call the Xianyu order detail API.

#### Scenario: 成功获取订单详情

**Given** 系统配置了有效的闲鱼API凭证(appKey和appSecret)
**When** 用户请求通过有效的订单号获取订单详情
**Then** 系统应该:
- 使用正确的签名算法(MD5)调用闲鱼API
- 返回包含以下字段的订单信息:
  - receiver_name (收货人姓名)
  - receiver_mobile (收货人电话)
  - prov_name (省份)
  - city_name (城市)
  - area_name (地区)
  - town_name (街道)
  - address (详细地址)
  - buyer_eid (买家ID)
  - pay_amount (实付金额,单位:分)
  - order_no (订单号)

#### Scenario: 处理无效订单号

**Given** 系统配置了有效的闲鱼API凭证
**When** 用户请求通过无效或不存在的订单号获取订单详情
**Then** 系统应该:
- 捕获API返回的错误响应
- 返回包含错误信息的结构化错误对象
- 不抛出未处理的异常

#### Scenario: 处理API连接失败

**Given** 闲鱼API服务不可用或网络连接失败
**When** 用户请求获取订单详情
**Then** 系统应该:
- 捕获网络连接异常
- 返回友好的错误消息
- 记录详细的错误日志供调试

### Requirement: Xianyu API Credentials Configuration

The system MUST support secure configuration of Xianyu API credentials.

#### Scenario: 从环境变量加载凭证

**Given** 环境变量中设置了XIANYU_APP_KEY和XIANYU_APP_SECRET
**When** 系统初始化闲鱼API服务
**Then** 系统应该:
- 从环境变量读取API凭证
- 验证凭证不为空
- 如果凭证缺失,记录警告日志

### Requirement: Backend API Endpoint

The system MUST provide a REST API endpoint for fetching order details.

#### Scenario: 成功返回订单详情

**Given** 前端发送包含有效订单号的请求
**When** 后端接收到获取订单详情的请求
**Then** 系统应该:
- 验证订单号参数不为空
- 调用闲鱼API服务获取订单详情
- 返回JSON格式的订单信息
- HTTP状态码为200

#### Scenario: 参数验证失败

**Given** 前端发送请求但未包含订单号
**When** 后端接收到获取订单详情的请求
**Then** 系统应该:
- 返回400 Bad Request状态码
- 返回包含错误信息的JSON响应
- 错误消息应明确指出缺少订单号参数

#### Scenario: API调用失败后的错误传递

**Given** 闲鱼API返回错误或不可用
**When** 后端尝试获取订单详情
**Then** 系统应该:
- 返回500 Internal Server Error状态码
- 返回包含用户友好错误消息的JSON响应
- 不暴露敏感的API凭证或内部错误详情
