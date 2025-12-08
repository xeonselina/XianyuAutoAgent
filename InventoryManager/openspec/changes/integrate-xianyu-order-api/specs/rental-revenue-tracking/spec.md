# 规格: 租赁收入跟踪

## ADDED Requirements

### Requirement: Rental Model Extension

The Rental model MUST be extended to store order-related information.

#### Scenario: 添加订单金额字段

**Given** 系统需要跟踪租赁收入
**When** 创建或更新租赁记录
**Then** Rental模型应该:
- 包含order_amount字段(DECIMAL 10,2类型)
- 存储订单金额,单位为元
- 允许该字段为NULL(支持历史数据)
- 在to_dict()方法中包含order_amount

#### Scenario: 添加闲鱼订单号字段

**Given** 系统需要关联闲鱼订单和租赁记录
**When** 创建或更新租赁记录
**Then** Rental模型应该:
- 包含xianyu_order_no字段(VARCHAR 50类型)
- 存储闲鱼订单号
- 允许该字段为NULL(支持历史数据和手动输入的租赁)
- 在to_dict()方法中包含xianyu_order_no

#### Scenario: 添加买家ID字段

**Given** 系统需要存储买家标识
**When** 创建或更新租赁记录
**Then** Rental模型应该:
- 包含buyer_id字段(VARCHAR 100类型)
- 存储闲鱼买家EID
- 允许该字段为NULL
- 在to_dict()方法中包含buyer_id

### Requirement: Database Migration Script

The system MUST provide a database migration script to add new fields.

#### Scenario: 安全地添加新列

**Given** 现有数据库包含历史租赁记录
**When** 执行数据库迁移
**Then** 迁移脚本应该:
- 添加order_amount列,默认值为NULL
- 添加xianyu_order_no列,默认值为NULL
- 添加buyer_id列,默认值为NULL
- 不修改或删除现有数据
- 成功完成而不破坏现有功能

### Requirement: Revenue Statistics Enhancement

The rental statistics feature MUST include order amount data for revenue tracking.

#### Scenario: 计算总收入

**Given** 数据库中存在多条包含order_amount的租赁记录
**When** 用户请求查看指定时间段的租赁统计
**Then** 系统应该:
- 计算该时间段内所有租赁的总收入
  - 公式: SUM(order_amount) WHERE order_amount IS NOT NULL
- 在统计结果中包含total_revenue字段
- 显示有订单金额的租赁记录数量

#### Scenario: 处理NULL订单金额

**Given** 某些租赁记录没有order_amount(历史数据或手动创建)
**When** 系统计算收入统计
**Then** 系统应该:
- 忽略order_amount为NULL的记录
- 在统计中标注有多少记录缺少金额数据
- 不因NULL值而导致计算错误
- 可选地显示"X条记录缺少金额数据"的提示

#### Scenario: 按时间段统计收入

**Given** 用户指定了开始日期和结束日期
**When** 系统生成收入统计报告
**Then** 系统应该:
- 只统计start_date在指定范围内的租赁记录
- 计算该时间段的总收入
- 计算平均订单金额(排除NULL值)
- 返回包含以下信息的统计对象:
  - total_revenue: 总收入
  - average_order_amount: 平均订单金额
  - orders_with_amount: 有金额数据的订单数
  - orders_without_amount: 无金额数据的订单数

### Requirement: Rental API Response Extension

The rental record API response MUST include the new order-related fields.

#### Scenario: 获取单个租赁记录

**Given** 租赁记录包含订单信息
**When** 前端请求获取租赁详情
**Then** API响应应该包含:
- xianyu_order_no: 闲鱼订单号
- order_amount: 订单金额(元)
- buyer_id: 买家ID

#### Scenario: 获取租赁列表

**Given** 系统返回租赁记录列表
**When** 前端请求获取租赁列表
**Then** 每条租赁记录应该包含:
- xianyu_order_no字段
- order_amount字段
- buyer_id字段
- NULL值应返回为null而非空字符串

### Requirement: Backward Compatibility

The system MUST maintain full backward compatibility with historical data.

#### Scenario: 查询历史租赁记录

**Given** 数据库中存在没有订单金额的历史租赁记录
**When** 系统查询或显示这些记录
**Then** 系统应该:
- 正常显示历史记录
- 对于没有order_amount的记录,显示为"未设置"或留空
- 不因缺少订单信息而报错
- 所有现有功能(状态更新、延期等)继续正常工作

#### Scenario: 更新历史租赁记录

**Given** 用户编辑一条没有订单金额的历史租赁记录
**When** 用户更新记录但不提供订单号
**Then** 系统应该:
- 允许更新而不要求填写订单号
- 保持order_amount、xianyu_order_no、buyer_id为NULL
- 成功保存其他字段的更新
