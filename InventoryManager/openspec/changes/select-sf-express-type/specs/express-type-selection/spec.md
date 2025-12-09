# Spec: 顺丰快递类型选择

## Capability
express-type-selection

## Status
Draft

## Overview
为批量发货功能增加顺丰快递类型选择能力,允许用户为每个订单独立选择快递服务类型(特快/标快/半日达),系统在调用顺丰API下单时使用用户选择的类型。

## ADDED Requirements

### Requirement: 数据持久化
系统 SHALL 在 `rentals` 表中存储每个订单的顺丰快递类型ID (`express_type_id`)。

#### Scenario: 新增字段定义
- **Given** 数据库迁移脚本被执行
- **When** 在 `rentals` 表中增加 `express_type_id` 字段
- **Then** 字段类型为 `INTEGER`,默认值为 `2`,并包含注释 "顺丰快递类型ID (1=特快,2=标快,6=半日达)"

#### Scenario: 现有记录默认值
- **Given** 数据库中存在未设置 `express_type_id` 的租赁记录
- **When** 迁移脚本执行后
- **Then** 这些记录的 `express_type_id` 自动设置为 `2` (标快)

---

### Requirement: 快递类型配置
系统 SHALL 支持三种顺丰快递类型配置,对应顺丰API的 `expressTypeId` 参数。

#### Scenario: 支持的快递类型
- **Given** 用户需要选择快递类型
- **When** 系统提供快递类型选项
- **Then** 可选值包括:
  - `1` = 特快 (时效最快,成本最高)
  - `2` = 标快 (标准时效,性价比高,默认推荐)
  - `6` = 半日达 (当日/次日达,适合本地配送)

#### Scenario: 默认快递类型
- **Given** 新创建的租赁订单
- **When** 未明确设置快递类型
- **Then** 默认使用 `2` (标快)

---

### Requirement: 前端快递类型选择器
系统 SHALL 在批量发货页面的订单列表中为每个订单提供快递类型下拉选择器。

#### Scenario: 显示快递类型列
- **Given** 用户打开批量发货页面并加载订单列表
- **When** 订单列表表格渲染
- **Then** 表格包含"快递类型"列,列宽为120px
- **And** 每行显示一个下拉选择器(el-select)
- **And** 选择器包含三个选项: "特快"、"标快"、"半日达"

#### Scenario: 选择器默认值
- **Given** 订单列表加载完成
- **When** 渲染快递类型选择器
- **Then** 如果订单的 `express_type_id` 已设置,显示对应的快递类型
- **And** 如果订单的 `express_type_id` 为空,默认显示"标快"

#### Scenario: 修改快递类型
- **Given** 用户查看订单列表
- **When** 用户点击某个订单的快递类型选择器并选择新类型
- **Then** 立即调用后端API更新该订单的快递类型
- **And** 成功时显示提示消息 "快递类型已更新"
- **And** 失败时显示错误提示

---

### Requirement: 快递类型更新 API
系统 SHALL 提供 API 端点用于更新租赁订单的快递类型。

#### Scenario: 成功更新快递类型
- **Given** 前端发送 `PATCH /api/shipping-batch/express-type` 请求
- **When** 请求包含有效的 `rental_id` 和 `express_type_id` 参数
- **And** `express_type_id` 的值在 `[1, 2, 6]` 范围内
- **And** 租赁记录存在
- **Then** 更新该租赁记录的 `express_type_id` 字段
- **And** 返回 `200 OK` 和响应体 `{ "success": true, "message": "快递类型已更新" }`

#### Scenario: 参数无效
- **Given** 前端发送 `PATCH /api/shipping-batch/express-type` 请求
- **When** `express_type_id` 不在 `[1, 2, 6]` 范围内(例如 `99`)
- **Then** 返回 `400 Bad Request` 和错误消息 "快递类型无效"

#### Scenario: 租赁记录不存在
- **Given** 前端发送 `PATCH /api/shipping-batch/express-type` 请求
- **When** 指定的 `rental_id` 在数据库中不存在
- **Then** 返回 `404 Not Found` 和错误消息 "租赁记录不存在"

#### Scenario: 缺少必要参数
- **Given** 前端发送 `PATCH /api/shipping-batch/express-type` 请求
- **When** 请求缺少 `rental_id` 或 `express_type_id` 参数
- **Then** 返回 `400 Bad Request` 和错误消息 "缺少必要参数"

---

### Requirement: 顺丰下单使用选定类型
系统 SHALL 在调用顺丰API下单时使用用户为订单选择的快递类型。

#### Scenario: 使用订单的快递类型
- **Given** 租赁订单的 `express_type_id` 已设置为 `6` (半日达)
- **When** 系统调用顺丰API为该订单下单
- **Then** 传递给顺丰API的 `expressTypeId` 参数值为 `6`
- **And** 日志记录 "使用快递类型: 6"

#### Scenario: 使用默认快递类型
- **Given** 租赁订单的 `express_type_id` 字段为空
- **When** 系统调用顺丰API为该订单下单
- **Then** 传递给顺丰API的 `expressTypeId` 参数值为 `2` (标快)
- **And** 日志记录 "使用快递类型: 2 (默认)"

#### Scenario: 替换硬编码值
- **Given** 旧代码中 `expressTypeId` 硬编码为 `1`
- **When** 实施快递类型选择功能后
- **Then** `expressTypeId` 从 `rental.express_type_id` 动态读取
- **And** 不再使用硬编码值

---

### Requirement: Rental模型包含快递类型
系统 SHALL 在 Rental 模型中定义 `express_type_id` 字段并在序列化时包含该字段。

#### Scenario: 模型字段定义
- **Given** `app/models/rental.py` 中的 Rental 模型
- **When** 定义模型字段
- **Then** 包含 `express_type_id = db.Column(db.Integer, default=2, comment='顺丰快递类型ID')`

#### Scenario: 序列化包含快递类型
- **Given** Rental 对象调用 `to_dict()` 方法
- **When** 序列化为字典
- **Then** 返回的字典包含 `'express_type_id': self.express_type_id` 键值对

---

### Requirement: 错误处理和用户反馈
系统 SHALL 在快递类型选择和更新过程中提供友好的错误提示。

#### Scenario: API调用失败提示
- **Given** 用户修改快递类型后调用API失败
- **When** API返回错误响应
- **Then** 前端显示 `ElMessage.error('更新快递类型失败')` 提示
- **And** 控制台记录详细错误信息

#### Scenario: 成功更新提示
- **Given** 用户修改快递类型后调用API成功
- **When** API返回成功响应
- **Then** 前端显示 `ElMessage.success('快递类型已更新')` 提示

---

## Non-Functional Requirements

### Performance
- 快递类型选择器变更后,API响应时间 SHALL 小于 500ms
- 加载订单列表时,快递类型数据 SHALL 随订单数据一起返回,不额外请求

### Usability
- 快递类型选择器 SHALL 使用清晰的中文标签(特快/标快/半日达)
- 默认值(标快) SHALL 在UI上明显可见,避免用户误选

### Reliability
- 快递类型更新失败时 SHALL 保持原有值,不影响订单其他信息
- 数据库迁移 SHALL 包含回滚脚本,确保可安全撤回

### Compatibility
- 现有未设置快递类型的订单 SHALL 自动使用默认值(标快)
- 快递类型功能 SHALL 不影响现有的运单号录入、预约发货等功能

---

## Constraints
- 快递类型ID SHALL 仅限于顺丰API支持的值: `1`, `2`, `6`
- 快递类型选择 SHALL 仅在批量发货页面提供,单个发货页面暂不支持
- 历史已发货订单的快递类型 SHALL 使用默认值填充,不追溯实际使用的类型

---

## Dependencies
- 依赖顺丰API的 `expressTypeId` 参数支持
- 依赖现有批量发货功能的订单列表UI

---

## Future Enhancements
以下功能不在本次变更范围内,可作为未来增强:
- 批量设置快递类型:一键为所有订单设置相同类型
- 智能推荐快递类型:根据收货地址自动推荐最优快递类型
- 快递类型价格显示:在选择器中显示不同类型的预估价格差异
- 快递类型统计:在批量发货页面显示各类型订单数量统计
