# Spec: 批量发货自动获取运单号

## MODIFIED Requirements

### Requirement: 预约发货时自动获取运单号

预约发货时，系统MUST调用顺丰API下单并自动获取运单号，无需手动扫描录入。系统SHALL从API响应中提取运单号并保存到数据库。

#### Scenario: 预约发货成功获取运单号

**Given** 用户已选择待发货订单，设置了预约时间
**When** 用户点击"预约发货"按钮
**Then** 系统调用顺丰API下单（`isGenWaybillNo=1`）
**And** 顺丰API返回 `apiResultCode=A1000` 且 `apiResultData.success=true`
**And** 从 `apiResultData.waybillNoInfoList[0].waybillNo` 提取运单号
**And** 将运单号保存到 `rental.ship_out_tracking_no` 字段
**And** 更新订单状态为 `shipped`
**And** 返回成功响应，包含运单号信息

**验证点**：
- 顺丰API请求中 `isGenWaybillNo` 必须为 `1`
- 响应中 `waybillNoInfoList` 数组必须有且只有一个元素
- 运单号必须非空且格式正确（字母数字组合）
- 数据库中 `ship_out_tracking_no` 字段已正确更新

#### Scenario: 顺丰API返回运单号为空

**Given** 用户已选择待发货订单，设置了预约时间
**When** 用户点击"预约发货"
**And** 顺丰API响应中 `waybillNoInfoList` 为空或不包含 `waybillNo`
**Then** 系统记录错误日志
**And** 返回失败响应，提示"顺丰API未返回运单号"
**And** 订单状态保持不变

#### Scenario: 顺丰API下单失败

**Given** 用户已选择待发货订单，设置了预约时间
**When** 用户点击"预约发货"
**And** 顺丰API返回 `apiResultCode != A1000` 或 `apiResultData.success=false`
**Then** 系统记录错误日志，包含错误码和错误信息
**And** 返回失败响应，提示具体的错误原因
**And** 订单状态保持不变
**And** 不保存运单号

### Requirement: 顺丰API参数正确配置

调用顺丰下单API时，系统MUST正确设置参数以启用自动生成运单号功能。系统SHALL设置isGenWaybillNo=1并确保waybillNoInfoList不包含预设运单号。

#### Scenario: 下单请求参数正确

**Given** 系统准备调用顺丰API下单
**When** 构建下单请求参数
**Then** `isGenWaybillNo` 必须为 `1`（自动生成运单号）
**And** `isUnifiedWaybillNo` 必须为 `1`（统一单号）
**And** `waybillNoInfoList` 数组包含一个元素 `{'waybillType': 1}`
**And** 不包含预设的 `waybillNo` 字段

**验证点**：
- 请求日志中记录完整的请求参数
- 参数符合顺丰API文档要求

### Requirement: API响应解析和错误处理

系统MUST正确解析顺丰API响应，提取运单号，并处理各种异常情况。系统SHALL验证响应格式并在解析失败时返回明确的错误信息。

#### Scenario: 成功解析运单号

**Given** 顺丰API返回成功响应
**And** 响应体为：
```json
{
  "apiResultCode": "A1000",
  "apiResultData": "{\"success\":true,\"waybillNoInfoList\":[{\"waybillType\":1,\"waybillNo\":\"SF1234567890\"}]}"
}
```
**When** 系统解析响应
**Then** 成功提取 `apiResultData` 字符串并解析为JSON
**And** 从 `waybillNoInfoList[0].waybillNo` 获取运单号 `SF1234567890`
**And** 返回成功结果，包含运单号

#### Scenario: apiResultData格式异常

**Given** 顺丰API返回的 `apiResultData` 不是有效的JSON字符串
**When** 系统尝试解析响应
**Then** 捕获JSON解析异常
**And** 记录错误日志，包含原始响应内容
**And** 返回失败响应，提示"顺丰API响应格式异常"

#### Scenario: waybillNoInfoList数组为空

**Given** 顺丰API返回成功，但 `waybillNoInfoList` 为空数组
**When** 系统尝试提取运单号
**Then** 记录警告日志
**And** 返回失败响应，提示"未获取到运单号"

#### Scenario: waybillNoInfoList包含多个元素

**Given** 顺丰API返回的 `waybillNoInfoList` 包含多个运单号
**When** 系统提取运单号
**Then** 记录警告日志，提示数组长度异常
**And** 仅使用第一个运单号（`waybillNoInfoList[0].waybillNo`）
**And** 正常处理下单流程

### Requirement: 批量发货的原子性

批量预约发货时，系统MUST独立处理每个订单，一个订单失败SHALL NOT影响其他订单。系统SHALL为每个订单使用独立的数据库事务。

#### Scenario: 批量发货部分成功

**Given** 用户选择了3个订单进行预约发货
**When** 第1个订单顺丰下单成功，获取运单号
**And** 第2个订单顺丰下单失败（如地址错误）
**And** 第3个订单顺丰下单成功，获取运单号
**Then** 返回批量发货结果：
  - `success_count`: 2
  - `failed_count`: 1
  - `results`: 包含每个订单的详细结果
**And** 成功的订单保存了运单号且状态为 `shipped`
**And** 失败的订单状态保持不变，不保存运单号

**验证点**：
- 数据库事务隔离，每个订单独立提交
- 失败订单的错误信息清晰记录

## REMOVED Requirements

### ~~Requirement: 手动扫描录入运单号~~

删除手动扫描录入运单号的功能，改为自动获取。

#### ~~Scenario: 扫描顺丰面单录入运单号~~

此场景已被移除，运单号由顺丰API自动生成。

### ~~Requirement: 扫描发货单二维码识别订单~~

删除扫描发货单二维码的功能，不再需要二维码识别订单。

#### ~~Scenario: 扫描发货单二维码弹出订单详情~~

此场景已被移除，预约发货时直接从订单列表选择。

## ADDED Requirements

### Requirement: 日志记录和监控

系统MUST详细记录顺丰API交互过程，便于排查问题和监控下单成功率。系统SHALL记录所有API调用的请求参数、响应内容和处理耗时。

#### Scenario: 记录完整的API交互日志

**Given** 系统调用顺丰API下单
**When** API调用开始、成功或失败时
**Then** 记录以下信息：
  - 请求时间戳
  - Rental ID
  - 预约发货时间
  - 请求参数（脱敏后）
  - 响应状态码
  - 响应内容（脱敏后）
  - 提取的运单号
  - 处理耗时

**验证点**：
- 日志级别为 INFO（成功）或 ERROR（失败）
- 日志格式统一，便于检索
- 敏感信息（如密钥）已脱敏

#### Scenario: 监控下单成功率

**Given** 系统已处理多次预约发货
**When** 查看系统日志或监控面板
**Then** 可以统计：
  - 总下单次数
  - 成功次数
  - 失败次数及失败原因分布
  - 平均响应时间

**关联能力**：
- 可选：后续可集成到监控系统（如Prometheus）
