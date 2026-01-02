# Spec: Gantt Conflict Indicators

Visual warning system for the Gantt chart that automatically detects and highlights scheduling conflicts between consecutive rentals with tight turnaround times and non-local destinations.

## ADDED Requirements

### Requirement: Detect scheduling conflicts between consecutive rentals
系统MUST自动检测同一设备上相邻租赁之间的档期冲突，基于时间间隔和目的地位置。

#### Scenario: 检测到档期冲突 - 时间紧且非广东地址

**Given** 甘特图显示设备A的租赁数据
**And** Rental 1: `end_date = "2025-01-10"`, `destination = "北京市朝阳区"`
**And** Rental 2: `start_date = "2025-01-12"`, `destination = "上海市浦东新区"`
**When** 系统计算相邻租赁之间的时间间隔
**Then** 时间间隔 = 2天 (≤ 4天)
**And** Rental 1 的目的地不包含"广东" ✓
**And** Rental 2 的目的地不包含"广东" ✓
**And** 系统标记 Rental 1 为存在档期冲突
**And** 在 Rental 1 的租赁条右上角显示黄色 ⚠️ 图标

**验证点**:
- 冲突检测基于 `start_date` 和 `end_date`（不是 `ship_out_time` 或 `ship_in_time`）
- 只在**前一个租赁**（Rental 1）上显示警告图标
- 时间间隔计算：`next.start_date - current.end_date` 以天为单位

#### Scenario: 不显示冲突 - 两个租赁都在广东

**Given** 甘特图显示设备B的租赁数据
**And** Rental 1: `end_date = "2025-01-10"`, `destination = "广东省广州市天河区"`
**And** Rental 2: `start_date = "2025-01-12"`, `destination = "广东省深圳市南山区"`
**When** 系统计算相邻租赁之间的时间间隔
**Then** 时间间隔 = 2天 (≤ 4天)
**And** Rental 1 的目的地包含"广东" ✓
**And** Rental 2 的目的地包含"广东" ✓
**And** 系统**不标记**为档期冲突（因为都在广东省内）
**And** Rental 1 上**不显示** ⚠️ 图标

**验证点**:
- 广东省内的短时间间隔不算冲突
- 使用简单的字符串包含检查：`destination.includes('广东')`

#### Scenario: 不显示冲突 - 时间间隔充足（>4天）

**Given** 甘特图显示设备C的租赁数据
**And** Rental 1: `end_date = "2025-01-10"`, `destination = "北京市朝阳区"`
**And** Rental 2: `start_date = "2025-01-16"`, `destination = "上海市浦东新区"`
**When** 系统计算相邻租赁之间的时间间隔
**Then** 时间间隔 = 6天 (> 4天)
**And** 系统**不标记**为档期冲突（时间充足）
**And** Rental 1 上**不显示** ⚠️ 图标

**验证点**:
- 超过4天的间隔不算冲突，即使目的地都不在广东

#### Scenario: 检测到冲突 - 其中一个租赁在广东

**Given** 甘特图显示设备D的租赁数据
**And** Rental 1: `end_date = "2025-01-10"`, `destination = "广东省广州市"`
**And** Rental 2: `start_date = "2025-01-13"`, `destination = "北京市朝阳区"`
**When** 系统计算相邻租赁之间的时间间隔
**Then** 时间间隔 = 3天 (≤ 4天)
**And** Rental 1 的目的地包含"广东" ✓
**And** Rental 2 的目的地**不包含**"广东" ✓
**And** 系统标记 Rental 1 为存在档期冲突（因为下一个租赁不在广东）
**And** 在 Rental 1 的租赁条右上角显示黄色 ⚠️ 图标

**验证点**:
- 冲突规则：`!A.destination.includes('广东') OR !B.destination.includes('广东')`
- 只要有一方不在广东，且时间紧，就算冲突

#### Scenario: 边界情况 - 同一天周转（间隔0天）

**Given** 甘特图显示设备E的租赁数据
**And** Rental 1: `end_date = "2025-01-10"`, `destination = "上海市"`
**And** Rental 2: `start_date = "2025-01-10"`, `destination = "杭州市"`
**When** 系统计算相邻租赁之间的时间间隔
**Then** 时间间隔 = 0天 (≤ 4天)
**And** 两个租赁的目的地都不包含"广东"
**And** 系统标记 Rental 1 为存在档期冲突
**And** 显示 ⚠️ 图标

**验证点**:
- 同一天结束和开始算作0天间隔
- 0 ≤ 4，因此触发冲突检测

#### Scenario: 边界情况 - 目的地为空或null

**Given** 甘特图显示设备F的租赁数据
**And** Rental 1: `end_date = "2025-01-10"`, `destination = null`
**And** Rental 2: `start_date = "2025-01-12"`, `destination = ""`
**When** 系统计算相邻租赁之间的时间间隔
**Then** 时间间隔 = 2天 (≤ 4天)
**And** 系统将 null 或空字符串视为**不包含**"广东"
**And** 系统标记 Rental 1 为存在档期冲突
**And** 显示 ⚠️ 图标

**验证点**:
- 空目的地 = 未知物流风险 = 应该警告
- 使用 `destination?.includes('广东') ?? false` 进行安全检查

#### Scenario: 排除已取消的租赁

**Given** 甘特图显示设备G的租赁数据
**And** Rental 1: `end_date = "2025-01-10"`, `status = "cancelled"`, `destination = "北京市"`
**And** Rental 2: `start_date = "2025-01-12"`, `status = "shipped"`, `destination = "上海市"`
**When** 系统执行冲突检测
**Then** 系统**过滤掉** `status = 'cancelled'` 的租赁
**And** 不计算 Rental 1 和 Rental 2 之间的冲突
**And** Rental 1 上**不显示** ⚠️ 图标（因为已取消）

**验证点**:
- 已取消的租赁不参与冲突检测
- 过滤条件：`rental.status !== 'cancelled'`

### Requirement: Display visual warning icon on conflicting rentals
甘特图MUST在存在档期冲突的租赁条上显示黄色警告图标⚠️。

#### Scenario: 警告图标显示在租赁条右上角

**Given** Rental A 被标记为存在档期冲突
**When** 甘特图渲染 Rental A 的租赁条（棕色 rental-period bar）
**Then** 在租赁条的右上角显示 ⚠️ emoji 图标
**And** 图标位置：`position: absolute; top: 2px; right: 2px;`
**And** 图标大小：`font-size: 16px`
**And** 图标有黄色发光效果：`filter: drop-shadow(0 0 2px rgba(255, 193, 7, 0.6))`
**And** 图标层级高于租赁条内容：`z-index: 10`

**验证点**:
- 图标不遮挡客户名称和电话号码
- 图标清晰可见，易于识别
- 图标与租赁条对齐，不超出边界

#### Scenario: 鼠标悬停图标时的交互效果

**Given** 租赁条上显示 ⚠️ 警告图标
**When** 用户将鼠标悬停在图标上
**Then** 图标放大至 120% 大小：`transform: scale(1.2)`
**And** 发光效果增强：`filter: drop-shadow(0 0 4px rgba(255, 193, 7, 0.9))`
**And** 过渡动画时长：`transition: transform 0.2s`
**And** 鼠标指针变为 pointer：`cursor: pointer`

**验证点**:
- 悬停效果流畅，无卡顿
- 视觉反馈明确，用户知道图标可点击

#### Scenario: 点击警告图标显示冲突详情

**Given** 租赁条上显示 ⚠️ 警告图标
**When** 用户点击警告图标
**Then** 阻止事件冒泡到父元素：`@click.stop`
**And** 触发 tooltip 显示，展示冲突详情
**And** **不触发**租赁条的编辑对话框（因为使用了 `.stop` 修饰符）

**验证点**:
- 点击图标只显示 tooltip，不打开编辑对话框
- Tooltip 内容包含冲突警告信息

### Requirement: Show conflict details in rental tooltip
租赁信息提示框MUST显示档期冲突的详细信息，包括时间间隔和目的地。

#### Scenario: Tooltip显示冲突警告信息

**Given** Rental X 存在档期冲突：
  - 下一个租赁距离结束 2 天
  - 当前目的地："北京市朝阳区"
  - 下一个目的地："上海市浦东新区"
**When** 用户悬停在 Rental X 的租赁条或点击 ⚠️ 图标
**Then** Tooltip 显示以下冲突信息：
  ```
  ⚠️ 档期冲突警告
  下一个租赁距离本次结束仅 2 天
  目的地: 北京市朝阳区 → 上海市浦东新区
  建议调整档期或确认物流时效
  ```
**And** 冲突警告部分使用浅黄色背景：`background-color: #FFF9E6`
**And** 警告文字使用深橙色强调：`color: #FF6F00`

**验证点**:
- 冲突信息清晰易读
- 建议文案帮助用户理解下一步操作

#### Scenario: Tooltip在无冲突时不显示警告信息

**Given** Rental Y 不存在档期冲突
**When** 用户悬停在 Rental Y 的租赁条
**Then** Tooltip 显示常规信息（客户、电话、日期等）
**And** **不显示**冲突警告部分
**And** Tooltip 保持原有样式和布局

**验证点**:
- 无冲突时 tooltip 功能不受影响
- 不显示空白或占位的冲突警告区域

### Requirement: Optimize conflict detection performance
冲突检测MUST高效执行，避免影响甘特图渲染性能。

#### Scenario: 使用computed缓存冲突检测结果

**Given** 甘特图组件加载并显示20个设备，每个设备有10个租赁
**When** 租赁数据未发生变化
**Then** 冲突检测结果被缓存在 Vue `computed` 属性中
**And** 甘特图重新渲染时**不重新计算**冲突（使用缓存）
**When** 用户编辑某个租赁的日期或目的地
**Then** 只有**相关设备**的冲突检测结果重新计算
**And** 其他设备的冲突检测使用缓存结果

**验证点**:
- 使用 `computed(() => {...})` 进行响应式缓存
- 缓存key包含：`rental.id`, `rental.start_date`, `rental.end_date`, `rental.destination`
- 性能测试：200个租赁的冲突检测 < 50ms

#### Scenario: 冲突检测算法时间复杂度

**Given** 设备有 N 个租赁记录
**When** 执行冲突检测
**Then** 算法步骤：
  1. 过滤已取消租赁：O(N)
  2. 按 start_date 排序：O(N log N)
  3. 遍历相邻租赁对：O(N)
**And** 总时间复杂度：O(N log N)
**And** 对于典型用例（N ≤ 10）：计算时间 < 5ms
**And** 对于极端用例（N = 100）：计算时间 < 50ms

**验证点**:
- 不使用嵌套循环（避免 O(N²) 复杂度）
- 排序只执行一次，结果可复用
- 边界条件处理不影响性能
