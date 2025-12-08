# Spec: 批量打印用户界面

## ADDED Requirements

### Requirement: Gantt Chart Batch Print Button

甘特图页面 MUST 在顶部工具栏显示"批量打印发货单"按钮,用于启动批量打印工作流。

#### Scenario: 用户打开甘特图

**Given** 用户已导航到甘特图页面
**When** 页面加载完成
**Then** 顶部工具栏必须显示标签为"📦 批量打印发货单"的按钮
**And** 该按钮必须与其他操作按钮并列显示

#### Scenario: 用户点击批量打印按钮

**Given** 用户正在查看甘特图
**When** 用户点击"批量打印发货单"按钮
**Then** 必须打开批量打印对话框
**And** 对话框必须显示日期范围选择器

---

### Requirement: Batch Print Dialog Date Range Selection

批量打印对话框 MUST 提供日期范围输入,供用户根据 `ship_out_time` 指定要打印的发货单。

#### Scenario: 用户选择有效的日期范围

**Given** 批量打印对话框已打开
**When** 用户选择开始日期"2025-01-01"
**And** 选择结束日期"2025-01-31"
**And** 点击"预览订单"按钮
**Then** 系统必须查询 `ship_out_time` 在选定日期之间的租赁记录
**And** 显示匹配的租赁记录列表
**And** 显示待打印订单的总数

#### Scenario: 用户选择无效的日期范围

**Given** 批量打印对话框已打开
**When** 用户选择的结束日期早于开始日期
**Then** 系统必须显示错误消息"结束日期必须晚于开始日期"
**And** "开始打印"按钮必须被禁用

#### Scenario: 日期范围内未找到订单

**Given** 批量打印对话框已打开
**When** 用户预览的日期范围内没有匹配的订单
**Then** 系统必须显示消息"该日期范围内未找到发货单"
**And** "开始打印"按钮必须被禁用

---

### Requirement: Batch Print View Multi-Order Rendering

批量打印视图页面 MUST 以适合打印的格式渲染所有选定的发货单,每个订单占据单独的页面。

#### Scenario: 用户确认批量打印

**Given** 用户已预览日期范围"2025-01-01"到"2025-01-31"的订单
**And** 有 5 个匹配的订单
**When** 用户点击"开始打印"按钮
**Then** 系统必须导航到 `/batch-shipping-order?start_date=2025-01-01&end_date=2025-01-31`
**And** 页面必须加载全部 5 条租赁记录
**And** 每个发货单必须使用标准发货单模板渲染
**And** 数据获取时必须显示加载指示器

#### Scenario: 批量打印视图显示操作栏

**Given** 批量打印视图已加载 5 个订单
**When** 页面显示时
**Then** 顶部必须显示操作栏
**And** 操作栏必须显示"共 5 个订单"
**And** 必须显示"返回甘特图"按钮
**And** 必须显示"打印所有发货单"按钮

---

### Requirement: Browser Print API Integration

批量打印功能 MUST 使用 `window.print()` 触发浏览器的原生打印对话框,并正确处理分页。

#### Scenario: 用户触发打印

**Given** 批量打印视图已渲染 5 个订单
**When** 用户点击"打印所有发货单"按钮
**Then** 浏览器的打印对话框必须打开
**And** 打印预览必须显示 5 个独立页面(每个订单一页)
**And** 每个发货单必须占据独立页面

#### Scenario: 应用打印样式

**Given** 浏览器打印对话框已打开
**When** 打印预览被渲染
**Then** 操作栏在打印输出中必须不可见
**And** 每个发货单必须应用 `page-break-after` 样式
**And** 最后一个发货单在其后必须不进行分页
**And** 所有内容必须适应 A4 页面边距

---

### Requirement: Data Completeness Validation

系统 MUST 在打印前检查每条租赁记录的完整性,并对缺失的关键数据显示警告。

#### Scenario: 所有订单数据完整

**Given** 批量打印视图已加载 5 个订单
**And** 所有订单都有完整的客户和设备信息
**When** 页面渲染时
**Then** 不得显示验证警告
**And** "打印所有发货单"按钮必须启用

#### Scenario: 部分订单数据缺失

**Given** 批量打印视图已加载 5 个订单
**And** 订单 #123 缺少客户电话
**And** 订单 #456 缺少收货地址
**When** 页面渲染时
**Then** 必须显示警告消息:"以下订单数据不完整"
**And** 警告必须列出:
  - "订单 #123: 缺少客户电话"
  - "订单 #456: 缺少收货地址"
**And** "打印所有发货单"按钮仍必须启用(允许带警告打印)

---

### Requirement: Loading and Error State Handling

批量打印对话框 MUST 在数据加载期间提供清晰的反馈,并优雅地处理错误。

#### Scenario: 加载订单中

**Given** 用户已点击"预览订单"
**When** API 请求正在进行中
**Then** 必须显示加载动画
**And** "开始打印"按钮必须被禁用
**And** 必须显示消息"正在加载订单..."

#### Scenario: API 请求失败

**Given** 用户已点击"预览订单"
**When** API 请求因网络错误失败
**Then** 必须显示错误消息:"加载订单失败,请检查网络连接"
**And** 必须显示"重试"按钮
**And** 点击"重试"必须重新尝试 API 请求

---

### Requirement: Chronological Order Sorting

批量打印视图 MUST 基于 `ship_out_time` 按时间顺序显示发货单,以匹配实际发货流程。

#### Scenario: 订单正确排序

**Given** 批量打印视图已加载以下订单:
  - 订单 #1: `ship_out_time` = "2025-01-15 10:00"
  - 订单 #2: `ship_out_time` = "2025-01-10 14:00"
  - 订单 #3: `ship_out_time` = "2025-01-12 09:00"
**When** 订单被渲染时
**Then** 显示顺序必须为:
  1. 订单 #2 (2025-01-10)
  2. 订单 #3 (2025-01-12)
  3. 订单 #1 (2025-01-15)
