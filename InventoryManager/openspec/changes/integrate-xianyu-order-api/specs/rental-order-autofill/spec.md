# 规格: 租赁表单自动填充

## ADDED Requirements

### Requirement: Order Number Field and Fetch Button

The rental form MUST include a Xianyu order number input field and a fetch button.

#### Scenario: 显示订单号输入字段

**Given** 用户打开创建或编辑租赁表单
**When** 表单加载完成
**Then** 系统应该:
- 在开始日期、结束日期和物流时间字段之后显示订单号输入字段
- 订单号字段应有清晰的标签"闲鱼订单号"
- 字段应接受数字字符串输入
- 在订单号字段旁边显示"拉取订单信息"按钮

#### Scenario: 启用拉取按钮条件

**Given** 用户在订单号字段中输入内容
**When** 订单号字段不为空
**Then** "拉取订单信息"按钮应该被启用
**And** 当订单号字段为空时,按钮应该被禁用

### Requirement: Automatic Form Field Population

The system MUST automatically fill form fields after successfully fetching order details.

#### Scenario: 成功自动填充所有字段

**Given** 用户输入了有效的闲鱼订单号
**And** 已输入开始日期、结束日期和物流时间
**When** 用户点击"拉取订单信息"按钮
**And** API成功返回订单详情
**Then** 系统应该:
- 使用receiver_name填充"客户姓名"字段
- 使用receiver_mobile填充"客户电话"字段
- 使用buyer_eid填充"买家ID"字段
- 使用 buyer_nick 填充“闲鱼 ID“字段
- 组合prov_name、city_name、area_name、town_name、address填充"收货地址"字段
  - 格式: "{prov_name}{city_name}{area_name}{town_name}{address}"
- 将pay_amount从分转换为元后填充"订单金额"字段
  - 转换公式: 元 = 分 / 100
- 保存订单号到rental记录

#### Scenario: 地址字段智能组合

**Given** 订单详情包含完整的地址信息
**When** 系统组合地址字段
**Then** 系统应该:
- 按正确顺序连接地址组件
- 处理某些地址组件可能为空的情况
- 去除多余的空格
- 如果所有地址组件都为空,destination字段应保持为空

#### Scenario: 部分字段缺失的处理

**Given** 订单详情中某些字段为空或null
**When** 系统尝试自动填充表单
**Then** 系统应该:
- 只填充有值的字段
- 保持原有字段值,如果API返回的对应字段为空
- 不因部分字段缺失而失败整个填充过程

### Requirement: User Feedback and Error Handling

The system MUST provide clear user feedback during order fetch operations.

#### Scenario: 显示加载状态

**Given** 用户点击了"拉取订单信息"按钮
**When** API请求正在进行中
**Then** 系统应该:
- 在按钮上显示加载指示器(如旋转图标)
- 禁用"拉取订单信息"按钮防止重复点击
- 可选地显示"正在获取订单信息..."的提示文本

#### Scenario: 成功提示

**Given** 订单信息成功获取并填充
**When** 所有字段填充完成
**Then** 系统应该:
- 显示成功消息"订单信息已成功获取"
- 使用绿色或成功样式的提示
- 自动填充的字段可以有视觉高亮(可选)

#### Scenario: 错误提示

**Given** 订单信息获取失败(如无效订单号、API错误)
**When** API返回错误响应
**Then** 系统应该:
- 显示具体的错误消息
- 使用红色或错误样式的提示
- 错误消息应包含可能的解决方案(如"请检查订单号是否正确")
- 保持表单字段不变,不覆盖用户已输入的数据

#### Scenario: 网络错误处理

**Given** 发生网络连接问题
**When** API请求失败
**Then** 系统应该:
- 显示"网络连接失败,请稍后重试"消息
- 允许用户重新尝试
- 提示用户可以手动输入信息

### Requirement: Data Overwrite Confirmation

The system SHALL consider user confirmation before overwriting existing form data.

#### Scenario: 表单字段已有数据时的警告

**Given** 用户已在某些字段中输入了数据(如客户姓名、电话)
**When** 用户点击"拉取订单信息"按钮
**Then** 
- 直接覆盖现有数据(简化实现)
- 显示提示说明已覆盖的字段