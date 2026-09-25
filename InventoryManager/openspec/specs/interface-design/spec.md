# PC 与移动端交互外壳

## Purpose

从两端 Router、App、共享头部及页面模板反推可见导航和页面结构。业务字段、状态与接口由对应功能规格定义；本规格让另一项目能复刻用户看到的页面骨架与导航流程。

## Requirements

### Requirement: PC 租户页面共用固定高度外壳

已登录 PC 业务页面 MUST 采用顶部 `AppHeader` 加可滚动主内容：根容器高 `100vh`、纵向 flex，主区域独立滚动。未登录／公开路由不显示租户头部。头部约 42px 高、白色半透明背景、底边线，左侧显示店铺名和当前仓库，中间四个主导航“档期管理、设备管理、统计、收货发货”，右侧账户弹出菜单；当前业务子页维持对应主导航高亮。多仓显示“全部仓库”及具体仓库选择，单仓只显示名称。账户菜单显示手机号和角色，管理员有“店铺设置”，密码模式有“账号安全”，均可退出。宽度小于 1080px 压缩间距，低于 760px 可横向滚动头部。

#### Scenario: 从验货进入批量发货
- **WHEN** 用户从 `/inspection-records` 转到 `/batch-shipping`
- **THEN** 两页仍高亮“收货发货”，仓库选择保持租户 store 中的值

### Requirement: PC 甘特主工作区按工具栏、提醒、筛选和时间网格排列

`/` MUST 先展示周导航（上周、今天、下周、跳日期）、当前区间、预定设备、待归还数量、客户历史和“档期操作”（一键重排、刷新）；其下是闲鱼订单提醒条及待归还抽屉，再下方是客户／地址搜索、型号、设备名、生命周期筛选，最后是日期列与设备行。日期表头展示空闲、主设备寄出、附件寄出、手柄数量；点击寄出数字筛选对应日期的设备。设备行高 94px，采用虚拟滚动；日期窗口是当前日期前 5 天至后 10 天。默认生命周期筛选 `active`。全仓库视图下设备行和一键重排只读／禁用。

#### Scenario: 默认进入甘特
- **WHEN** 有 active 租户的用户打开 `/`
- **THEN** 看见当前日期附近 16 天的表头、active 设备行及待归还／闲鱼提醒入口

### Requirement: 甘特编辑任务以对话框完成

PC 甘特 MUST 通过 `BookingDialog` 新建租赁、`EditRentalDialogNew` 修改、`RentalConfirmationDialog` 查看确认、`BatchPrintDialog` 批量打印、`CustomerHistoryDialog` 查看历史、`ScheduleReorderDialog` 重排、`PendingReturnsDrawer` 处理待归还。关闭或保存后仍处在甘特页并刷新相关数据；接收闲鱼漏单提醒的“补录”事件时，预定框需带订单号和店铺 ID。对话框里的字段和错误行为详见业务规格。

#### Scenario: 从漏单提醒补录
- **WHEN** 点击闲鱼提醒的补录操作
- **THEN** 打开预定设备对话框并预填该订单号与所属店铺，不切到另一个租户或店铺

### Requirement: PC 独立页面与导航卡承担明确任务

`/devices` MUST 在设备列表与型号库之间切换，可添加、查询、编辑、删除、标售、移仓；`/operations` 是“收货发货”入口，分发货处理（批量发货、接力发货）和收货与核验（验货验机、物流查询）四张卡；`/settings` 有“团队成员、仓库与发货、闲鱼 API”三标签。`/rental-stats` 提供按周／月、型号、日期筛选、CSV 导出、周期表和 X200U 三场景预测表；出租率颜色阈值为 ≥80% 绿、50–80% 黄、<50% 红。`/statistics` 重定向到 `/rental-stats`。

#### Scenario: 管理员打开设置
- **WHEN** tenant admin 进入 `/settings`
- **THEN** 看到三个标签及各自配置组件；operator 由路由守卫跳受限页

### Requirement: PC 发货和收货工作台保留专用页面

PC MUST 提供 `/batch-shipping`（日期窗口、订单列表、合包预览、选择、批量打印／预约）、`/batch-shipping-order`（合并出货单与打印／重试）、`/shipping/:id`（单笔发货单）、`/relay-management`（接力查询与维护）、`/inspection`（新建／编辑验货）、`/inspection-records`（列表及筛选）、`/sf-tracking`（时间筛选、列表、批量刷新与轨迹详情）。这些页面仍共享顶部租户和仓库上下文，不应改成互不相通的孤立表单。

#### Scenario: 操作入口到验货
- **WHEN** 从 `/operations` 的“验货验机”卡进入
- **THEN** 跳 `/inspection-records`，可再进入 `/inspection` 创建或编辑记录

### Requirement: 移动端有独立导航和底部主工作台

移动端 MUST 使用 `/mobile/` 作为 history base，在顶部显示店铺、仓库、`Admin/Operator` 和退出；有多仓时同样可选“全部仓库”。`/mobile/gantt`、`/mobile/batch-shipping`、`/mobile/relay` 显示固定底部标签“甘特图、批量发货、接力”，其它流程页不显示标签；内容区需为 50px tabbar 加安全区预留底部空间。甘特和批量发货视图在切换主标签时 keep-alive 保存局部状态。Vant 主色 `#409eff`。

#### Scenario: 从移动甘特进入编辑
- **WHEN** 点击订单进入 `/mobile/edit-rental/:id`
- **THEN** 底部三标签隐藏，保存或返回后回到移动端路径，不进入 PC 编辑弹窗

### Requirement: 移动业务路径都能独立刷新恢复

移动端 MUST 有 `/mobile/gantt` 时间窗与设备排期网格、`/mobile/batch-shipping` 候选卡和选择打印／预约、`/mobile/create-rental`、`/mobile/edit-rental/:id`、`/mobile/device-status`、`/mobile/search`、`/mobile/customer-history`、`/mobile/relay`。编辑／新建使用移动表单、底部弹层和 Vant 交互，而非把 PC 大表直接缩窄。每条路径在浏览器刷新后仍加载对应页面；过期登录恢复回原移动路径。

#### Scenario: 刷新客户历史
- **WHEN** 用户在 `/mobile/customer-history` 直接刷新
- **THEN** 服务端返回移动 SPA 壳并由移动 Router 重建客户历史页

### Requirement: PC 甘特工具栏与筛选默认状态可复刻

PC 甘特时间窗口 MUST 以 store 当前日期前 5 天至后 10 天显示共 16 列；“上周／今天／下周”与日期选择器控制 store 日期，点击某日表头只更新选中日。上方动作按顺序为“预定设备”“待归还”（非零时角标）、“客户历史”和“档期操作”下拉，后者含“一键重排档期”“刷新档期”；视口不宽于 1280px 时客户历史移进下拉。筛选行从左到右为“搜索租赁人名/地址”、型号单选、设备名称多选、设备状态单选及“清除过滤”；状态默认 `active`，可选 `all,sold,damaged,decommissioned,retired`。清除后恢复空关键词／型号／名称及 `active`。搜索输入有 300ms 防抖。每日统计仅在数量大于 0 时显示“闲／寄／附寄／手柄”；点击寄出数字按当天相关设备名称前缀设名称筛选并提示结果。

#### Scenario: 宽度缩小时打开客户历史
- **WHEN** PC 甘特宽度从大于 1280px 降至 1280px 以下
- **THEN** 独立客户历史按钮隐去，档期操作菜单出现“客户历史”，原客户历史对话框功能仍可打开

### Requirement: 移动甘特、搜索和客户历史保持独立交互

移动甘特 MUST 默认从今天前 2 天起显示 14 天，左／右箭头每次平移 7 天；顶部还有型号筛选 action sheet、搜索、客户历史、设备状态和“新建”入口。点击档期条开底部订单详情；切换仓库时清除选中订单并重新读甘特与每日统计，过期请求不能覆盖新仓数据。移动 `/search` 默认显示输入提示，输入电话或地址后 300ms 防抖请求 `/api/rentals/search`（`per_page=50`、当前仓库），结果卡展示客户、状态、电话、起止日和地址，点卡进移动编辑。移动 `/customer-history` 先按电话／姓名／闲鱼 ID 搜候选，展示掩码电话与订单数；选候选后展示租赁组合、价格、日均价、起止日与天数，返回键先回候选页再回上一业务页。

#### Scenario: 移动端切仓时旧甘特请求晚返回
- **WHEN** A 仓统计请求未结束，用户切 B 仓且 B 仓请求先完成
- **THEN** 视图只保留 B 仓的设备与每日统计，A 仓结果不能写回当前页

### Requirement: 移动设备状态、批量发货和接力有固定默认筛选

`/mobile/device-status` MUST 默认展示全部主设备，六个生命周期标签依次为“全部、使用中、已售出、已停用、已损坏、已退役”；设备卡显示名称、序列号、型号及可点击生命周期标签，全仓视图及非当前仓设备不可修改。移动批量发货默认查今天至明天，状态筛选为“全部、待发货、已预约”；卡按 `shipping_group_id` 合包，显示每组台数与一票标识，可选择整组或全选。已发货／已寄回／已完成、接力后单及非当前仓租赁不可勾选；底部操作仅在具体仓且已选时出现“预约发货”“打印面单”，预约默认明天 10:00。移动接力默认筛选 pending/notified/agreed/shipped、今天前 3 天到后 5 天、每页 50 条；可切今天到后 15 天或自定义，至少保留一个状态，支持加载更多、人工标记、单条及当前页批量轨迹刷新。

#### Scenario: 全仓移动视图查看但不能执行
- **WHEN** 用户切到“全部仓库”并在移动设备状态页点一台设备状态，或在批量发货页选择订单
- **THEN** 设备状态操作提示先选具体仓；发货页面不把任何订单计入可提交选择，底部预约／打印栏不出现

## 页面到组件映射

| 入口 | 核心组件／可见区块 |
|---|---|
| PC `/` | `GanttChart`、`GanttRow`、`XianyuOrderAlertBar`、`PendingReturnsDrawer`、新建／编辑／确认／打印／客户历史／重排弹窗 |
| PC `/devices` | `DeviceManagementView`、`DeviceModelLibrary`、`WarehouseMovementDialog` |
| PC `/settings` | `MemberSettings`、`WarehouseSettings`、`XianyuShopSettings` |
| PC `/operations` | 四张路由卡，浅灰页面背景、白卡、蓝／橙／绿／紫图标 |
| PC `/rental-stats` | 过滤器、出租率图例、周期表、X200U 三场景表及汇总 |
| PC `/inspection*` | `DeviceSearchInput`、`RentalInfoCard`、`ChecklistForm`、`InspectionRecordCard` |
| 移动甘特 | `GanttGrid`、`RentalBottomSheet`、`RentalConfirmationPopup`，导航栏时间窗口与筛选 |
| 移动创建／编辑 | `BookingDeviceSelector` 和适配手机的订单表单／确认弹层 |
| 移动批量发货／接力 | `BatchShippingCard`、`RelayCaseCard`、`RelayStatusSheet`、`ManualRelaySheet` |

PC 默认系统字体栈为 Apple system、BlinkMacSystemFont、Segoe UI、Roboto、Helvetica Neue、Arial；常用文字色 `#101828/#344054/#667085`，浅灰背景 `#f7f9fc`，主蓝 `#175cd3/#2e90fa`。这些是当前页面可见的基础值；单页的特殊尺寸和打印样式以对应组件 CSS 与打印规格为准。

## 验收与代码依据

复刻验收需要在桌面及手机宽度下逐页比对：导航顺序、仓库切换、默认筛选、按钮名称与可用条件、弹窗与底部栏、日期列、表格字段、空态、错误提示、路由刷新和打印视图。依据：`frontend/src/{App.vue,router/index.ts,components/AppHeader.vue,components/GanttChart.vue,views/*}`、`frontend-mobile/src/{App.vue,router/index.ts,views/*,components/*}`。视觉 99% 仍需固定 viewport 的截图对照；此规格本身不声称已完成像素级验收。
