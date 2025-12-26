# Spec: Single Rental Shipping

UI and API capability for shipping a single rental to Xianyu directly from the edit dialog.

## ADDED Requirements

### Requirement: User can ship single rental to Xianyu from edit dialog
用户MUST能够从租赁编辑对话框直接发货到闲鱼，无需切换到批量发货页面。

#### Scenario: 用户点击发货按钮成功同步到闲鱼

**Given** 用户在租赁编辑对话框中查看一条租赁记录
**And** 该租赁记录有 `xianyu_order_no` 和 `ship_out_tracking_no`
**When** 用户点击 "发货到闲鱼" 按钮
**Then** 系统调用 POST `/api/rentals/{rental_id}/ship-to-xianyu`
**And** 后端调用 `XianyuOrderService.ship_order(rental)` 方法
**And** 闲鱼API返回成功 (code=0)
**And** 租赁状态更新为 `shipped`（如果之前不是）
**And** 数据库事务提交
**And** 前端显示成功提示："已成功发货到闲鱼"
**And** 前端刷新租赁数据显示最新状态

**验证点**:
- 按钮在API调用期间显示加载状态
- 成功后租赁状态为 `shipped`
- 数据库中 `ship_out_time` 字段已设置（如果之前为空）

#### Scenario: 租赁记录缺少必要字段时按钮禁用

**Given** 用户在租赁编辑对话框中查看一条租赁记录
**And** 该租赁记录缺少 `xianyu_order_no` 或 `ship_out_tracking_no`
**When** 用户查看对话框中的按钮
**Then** "发货到闲鱼" 按钮显示为禁用状态（灰色）
**And** 鼠标悬停时显示提示："缺少闲鱼订单号或快递单号"

**验证点**:
- 按钮的 `disabled` 属性为 true
- 禁用状态下无法点击

#### Scenario: 闲鱼API返回错误

**Given** 用户在租赁编辑对话框中查看一条租赁记录
**And** 该租赁记录有 `xianyu_order_no` 和 `ship_out_tracking_no`
**When** 用户点击 "发货到闲鱼" 按钮
**And** 闲鱼API返回错误 (code != 0, msg="订单已发货")
**Then** 后端不更新租赁状态
**And** 后端回滚数据库事务
**And** 后端返回错误响应: `{"success": false, "message": "闲鱼发货失败: 订单已发货"}`
**And** 前端显示错误提示包含闲鱼返回的错误信息

**验证点**:
- 租赁状态未改变
- 数据库未提交任何更改
- 错误消息清晰展示给用户

### Requirement: Reuse existing ship_order service method
系统MUST复用现有的XianyuOrderService.ship_order()方法，确保批量发货和单个发货使用相同的业务逻辑。

#### Scenario: 单个发货和批量发货使用相同的闲鱼API

**Given** 系统有批量发货功能和单个发货功能
**When** 任一功能被触发
**Then** 两者都调用 `XianyuOrderService.ship_order(rental)` 方法
**And** 该方法向闲鱼发送相同格式的请求: POST `/api/open/order/ship`
**And** 请求体包含: `order_no`, `waybill_no`, `express_code`, `express_name`

**验证点**:
- 不存在重复的闲鱼API调用代码
- 单个发货和批量发货的日志格式一致
- 错误处理逻辑一致

### Requirement: Prevent double submission with loading state
前端MUST在API调用期间禁用发货按钮并显示加载状态，防止重复提交。

#### Scenario: 防止用户快速重复点击发货按钮

**Given** 用户在租赁编辑对话框中
**And** "发货到闲鱼" 按钮可用
**When** 用户点击 "发货到闲鱼" 按钮
**Then** 按钮立即进入加载状态（显示 loading spinner）
**And** 按钮的 `disabled` 属性设置为 true
**And** 用户无法再次点击按钮
**When** API响应返回（成功或失败）
**Then** 按钮恢复正常状态（移除 loading spinner 和 disabled）

**验证点**:
- `shippingToXianyu` 状态变量在调用期间为 true
- 按钮文本或图标显示加载指示器
- 连续点击不会发送多个API请求

### Requirement: Log all ship operations for traceability
后端MUST记录所有发货操作的日志，包括成功和失败的情况，便于追踪和调试。

#### Scenario: 记录成功的发货操作

**Given** 用户触发单个发货
**When** 闲鱼API调用成功
**Then** 系统记录 INFO 级别日志，包含:
  - Rental ID
  - 闲鱼订单号
  - 快递单号
  - 操作结果: "已成功发货到闲鱼"
  - 时间戳

**验证点**:
- 日志可通过 rental_id 检索
- 日志包含足够的上下文信息用于审计

#### Scenario: 记录失败的发货操作

**Given** 用户触发单个发货
**When** 闲鱼API调用失败（如：网络超时、业务错误）
**Then** 系统记录 ERROR 级别日志，包含:
  - Rental ID
  - 闲鱼订单号
  - 快递单号
  - 错误类型和详细错误信息
  - 时间戳

**验证点**:
- 错误日志包含完整的异常堆栈（如适用）
- 敏感信息（如API密钥）已脱敏

### Requirement: Provide clear feedback and refresh data after operation
前端MUST在操作完成后显示明确的成功或失败反馈，并刷新租赁数据。

#### Scenario: 发货成功后显示通知并刷新数据

**Given** 用户点击 "发货到闲鱼" 按钮
**When** API返回成功响应
**Then** 前端显示 ElMessage 成功通知: "已成功发货到闲鱼"
**And** 前端调用 `ganttStore.getRentalById(rental.id)` 获取最新数据
**And** 对话框中的租赁状态更新为 `shipped`

**验证点**:
- 通知显示在屏幕顶部，3秒后自动消失
- 租赁数据已刷新，状态显示为"已发货"

#### Scenario: 发货失败后显示错误通知

**Given** 用户点击 "发货到闲鱼" 按钮
**When** API返回错误响应: `{"success": false, "message": "闲鱼发货失败: 订单不存在"}`
**Then** 前端显示 ElMessage 错误通知: "发货失败: 订单不存在"
**And** 对话框中的租赁状态保持不变

**验证点**:
- 错误通知持续时间较长（如 5秒）
- 错误消息从后端响应中提取
