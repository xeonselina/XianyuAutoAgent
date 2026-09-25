# 甘特图、每日统计与档期重排

## Purpose

从甘特路由、服务、重排求解器和 PC／移动端甘特组件反推。租赁具体创建／编辑规则在 `rental-management`。

## Requirements

### Requirement: 甘特只列主设备与未取消主租赁

`GET /api/gantt/data` MUST 返回当前租户范围内的非库存附件设备及日期窗口重叠的主租赁，排除 `cancelled`；可按仓库筛选，缺少任一端日期时默认为本月首日到末日。响应为 `data:{devices,rentals,date_range:{start,end},today}`。每台设备内部也有其租赁列表，但编辑需另 GET 完整租赁详情。

#### Scenario: 有库存附件的订单
- **WHEN** 一个主机租赁带手机支架子租赁
- **THEN** 甘特设备行与顶层租赁列表只出现主机记录，主租赁的 `accessories` 展示两类附件

### Requirement: 两端甘特以仓库和窗口驱动刷新

PC MUST 提供按日期滚动的设备行、日统计、点击空档新建、点击租赁编辑、提醒和重排入口；移动端 MUST 提供仓库与日期导航、触摸租赁条查看底部详情、进入新建／编辑。两端切换仓库后刷新租赁，移动端关闭旧详情。移动条形图外层反映物流占用，内层反映租赁日期。

#### Scenario: 移动端切仓库
- **WHEN** 操作员在已打开某租赁详情时切换仓库
- **THEN** 详情关闭，读取新仓库甘特，旧仓库租赁不继续显示

### Requirement: 每日统计可一次读取日期范围

`GET /api/gantt/daily-stats` MUST 支持单日 `date` 或同时指定 `start_date,end_date` 的批量模式，可按 `device_model` 和仓库过滤。范围最多 366 天；结果每天有 `date,available_count,ship_out_count,accessory_ship_out_count`。仅 active 的主设备参加空闲设备统计；型号过滤按正式型号显示名匹配。

#### Scenario: 只给范围一端
- **WHEN** 请求只带 `start_date`
- **THEN** 返回 400“必须同时提供start_date和end_date”

### Requirement: 档期查找保留物流缓冲

`POST /api/rentals/find-slot` MUST 要求 `start_date,end_date,logistics_days,model,is_accessory`，可指定仓库；起止日可同一天。寄出日为起租日减 `1+logistics_days`，收回日为还租日加相同天数；查找占用使用寄出日 19:00 到收回日 12:00。只候选 active、指定主机／附件类型及正式型号 ID 的设备；找到返回第一台和全部可用设备、日期字符串及总数，无候选 404。创建 API 会用最终提交时间再次校验，因此此查询不预留设备。

#### Scenario: 两台候选
- **WHEN** 指定型号同仓有两台设备在计算区间空闲
- **THEN** 返回 `device,available_devices,total_available=2,ship_out_date,ship_in_date`

### Requirement: 重排先识别重叠接力关系

`POST /api/gantt/reorder/analyze` MUST 在具体仓库扫描未取消、寄出和收回时间均存在且尚有未来占用的主租赁，按设备和寄出时间排列。相邻两条的收回日期晚于下一条寄出日期时形成待确认重叠。每对有 `pair_key,overlap_days,status=bound/needs_confirmation,binding_id,can_separate,device,predecessor,successor`。仅未发货、寄出日不早于今天且型号可识别的主租赁可移动。

#### Scenario: 已绑定接力
- **WHEN** 两条相邻租赁日期重叠且有绑定记录
- **THEN** 分析结果标为 `bound` 并返回绑定 ID，不再视作未确认

### Requirement: 重排预览是零写入且所有待确认关系要有决定

预览请求 `decisions` 每项 MUST 给前单 ID、后单 ID 和 `action=keep/separate`，不可重复；所有 `needs_confirmation` 对必须处理。固定两单不能选择 `separate`。系统按型号和仓库建立档期块，在最多 3 秒求解时间内分配同型号设备、保留固定块、避免新重叠；返回各型号求解状态、设备变化、跳过记录、重叠关系与签名 token。预览不能修改租赁或接力绑定。

#### Scenario: 未处理一对冲突
- **WHEN** 请求预览漏掉一对 `needs_confirmation`
- **THEN** 返回 400“仍有未确认的重叠档期”，数据库不变

### Requirement: 重排执行校验快照并原子提交

`POST /api/gantt/reorder/execute` MUST 只接受预览 token；token 最长 600 秒，含求解器版本、日期、仓库、决定、分配与数据快照摘要。执行前锁定相关租赁、设备与绑定，重读快照、验证同型号与固定分配，事务内应用设备 ID 更换和接力关系，并写审计。token 过期、跨日或相关状态变化返回 409，所有写入回滚。

#### Scenario: 预览后租赁改期
- **WHEN** 预览和执行间任一相关租赁时间改变
- **THEN** 返回 409 要求重新预览，不能只应用仍可行的一部分

### Requirement: 甘特日期过滤与设备当前仓库、订单历史仓库分别计算

甘特列表 MUST 始终返回当前仓内全部主设备，不因它们当前生命周期不是 active 而从设备行消失；订单只返回未取消、无父租赁且 `start_date <= 窗口结束`、`end_date >= 窗口开始` 的记录。按仓库筛选时设备按当前 `devices.warehouse_id`，订单按其保存的 `rentals.warehouse_id`；移仓后历史订单可能仍在旧仓过滤结果，不能被偷偷改写。内嵌设备租赁仅含当前窗口内、仍挂在该设备上的主租赁；顶层租赁另含 booking、镜头组合和完整附件展示。

#### Scenario: 设备移仓后查看旧仓
- **WHEN** 设备从 A 仓移至 B 仓，而旧主租赁仍保存 A 仓履约记录
- **THEN** A 仓设备行不再列设备，A 仓顶层租赁历史仍按租赁仓库过滤；不能因此修改旧履约仓

### Requirement: 每日空闲与寄出数量使用不同候选集

`available_count` MUST 先以当前 active 主设备为候选，再扣除在当天零点至末刻与 `ship_out_time/ship_in_time` 相交、状态为 `not_shipped/scheduled_for_shipping/shipped/returned` 的唯一设备数；同设备重叠多单只扣一次。`ship_out_count` 与 `accessory_ship_out_count` 则按当天有 `ship_out_time` 且状态为 `not_shipped/scheduled_for_shipping` 的租赁行分别计数，不受 `available_count` 候选集合限制。仓库筛选寄出记录按租赁履约仓库；型号筛选附件寄出按其父主机型号判断。单日请求只返回当天统计对象；范围请求返回 `{start_date,end_date,stats:{YYYY-MM-DD:每日统计}}`。

#### Scenario: 同设备同日两条占用
- **WHEN** 一台 active 主设备有两条同一天重叠占用
- **THEN** 空闲数量只减 1；两条待寄出订单若都在当天寄出则寄出计数可为 2

### Requirement: 移动甘特显示十四列和两层档期条

移动 `GanttGrid` MUST 从 `windowStart` 连续显示 14 个日期列，设备名固定窄列，未加载显示 spinner、空设备显示“暂无设备数据”。每条订单用寄出到收回时间的半透明外条及起租到还租日期的实色内条，按窗口裁剪，点击内条打开详情；浮动标签显示客户名、手机号末四位与同单进度。状态色为待发货 `#c8860a`、已预约 `#1989fa`、已发货 `#07c160`、已寄回 `#7232dd`、已完成灰色；取消订单由后端列表排除。

#### Scenario: 档期跨移动窗口左边界
- **WHEN** 订单在 14 天窗口开始前寄出、窗口内起租
- **THEN** 外条从可见左边界开始，内条从起租日开始，点击内条仍打开该租赁

## HTTP 与响应细节

| 路径 | 关键数据 |
|---|---|
| `GET /api/gantt/data` | `start_date,end_date,warehouse_id` → 设备行、主租赁、日期窗口、今天 |
| `GET /api/gantt/daily-stats` | `date` 或成对 `start_date,end_date`，可选 `device_model,warehouse_id` |
| `POST /api/rentals/find-slot` | `{start_date,end_date,logistics_days,model,is_accessory,warehouse_id}`；无设备 404 |
| `POST /api/gantt/reorder/analyze` | `{warehouse_id}` → 重叠对列表 |
| `POST /api/gantt/reorder/preview` | `{warehouse_id,decisions:[{predecessor_rental_id,successor_rental_id,action}]}` → `{token,models,changes,skipped,overlaps}` |
| `POST /api/gantt/reorder/execute` | `{token}` → `{changes,relay_changes}`；过期／脏快照 409 |

每个甘特租赁摘要含 `id,booking,lens_combo,xianyu_order_no,xianyu_shop_id,device_id,warehouse_id,device_name,start_date,end_date,customer_name,customer_phone,destination,ship_out_tracking_no,ship_in_tracking_no,status,ship_out_time,ship_in_time,accessories`。设备行含型号与生命周期信息、内嵌租赁。甘特数据用**租赁日期窗口相交**过滤，与租赁列表的“完全包含”筛选不同。

## 代码依据与验收

依据：`app/routes/gantt_api.py`、`app/handlers/gantt_handlers.py`、`app/services/gantt/{gantt_service,reorder_service,reorder_solver,reorder_types}.py`、`frontend/src/components/GanttChart.vue`、`frontend-mobile/src/components/GanttGrid.vue`。验收覆盖跨月窗口、取消与附件排除、每日统计 366 天上限、查档期 19:00／12:00 边界、重排接力决定、预览零写入、脏 token 回滚和 PC／移动仓库切换。
