# 客户间设备接力

## Purpose

从接力 case／binding 模型、候选识别、状态 API、顺丰追踪和 PC／移动页面反推。接力表示前单客户直接把同一设备寄给后单客户，后单不得再由仓库重复批量发货。

## Requirements

### Requirement: 系统识别同设备相邻重叠订单

候选扫描 MUST 只取未取消、非附件、已有寄出时间的租赁，按设备、寄出时间、ID 升序排列。相邻两单如果前单未 completed、收回时间存在，且前单收回日期严格晚于后单寄出日期，则形成接力候选，`overlap_days` 为两日期差。列表还合并既有接力 case 和绑定，即使原档期后来变化仍保留运营记录并标出 `schedule_changed`。

#### Scenario: 绑定后改动日期
- **WHEN** 原先重叠的两单已绑定，之后时间改到不重叠
- **THEN** 接力管理列表仍可见这条记录并提示档期变化

### Requirement: 接力绑定禁止分叉

绑定 MUST 只连接两个不同的主租赁，同一设备且同一正式型号，前单寄出时间早于后单。一个前单最多一个后单、一个后单最多一个前单。进入 `agreed` 及更高状态时建立绑定；从已同意退回较低状态时删除该对绑定。与别的绑定冲突返回 409。

#### Scenario: 一笔后单被两个前单声明接力
- **WHEN** 第二个前单尝试绑定同一后单
- **THEN** 返回 409，不覆盖原绑定

### Requirement: 接力运营状态和里程碑明确

状态 MUST 是 `pending,notified,agreed,shipped,completed`。默认列表只看前四种，日期范围默认为今天前 3 天到后 5 天，分页默认 50、最多 100。case 记录通知、同意、寄出、完成时间；进入较高阶段填缺失的前序里程碑，退回较低阶段清除后序里程碑，并写审计日志。

#### Scenario: 从 pending 直接标 shipped
- **WHEN** 操作员提交状态 shipped 和顺丰单号
- **THEN** 通知、同意、寄出里程碑均有时间，绑定成立；不能缺单号

### Requirement: 接力寄出同步前后租赁与外部平台

首次进入 `shipped` MUST 要求顺丰运单号，将前单状态置 `returned`、后单寄出运单号写为该号码并置 `shipped`，必要时补后单寄出时间。内部事务提交后尝试闲鱼后单发货，同步结果独立返回 `xianyu_sync`；闲鱼失败不得撤销已经成立的内部接力发货事务。

#### Scenario: 闲鱼接口失败
- **WHEN** 接力内部寄出成功但闲鱼失败
- **THEN** 内部前后单状态与运单保留，响应标出外部同步失败，允许后续处理

### Requirement: 人工接力只允许当前单和下一单

人工候选 MUST 为同设备当前 `shipped/returned` 主租赁和下一条 `not_shipped/scheduled_for_shipping` 主租赁；选项展示设备、两单客户与配置以及不可建立原因。`POST /manual` 按设备 ID 锁定并复核候选，建立唯一绑定和 status=`agreed` 的 case，并记人工创建审计。档期在选择后变化则拒绝要求刷新。

#### Scenario: 当前设备无合适下一单
- **WHEN** 人工选择一个只有当前租赁的设备
- **THEN** 返回 400，不创建 case 或绑定

### Requirement: 接力顺丰查询可单条与批量刷新

仅 `shipped/completed` 且有顺丰单号的 case MUST 可查询物流；用后单手机号后四位向顺丰查询，保存状态、去重摘要、查询时间。批量刷新一次最多 100 条，逐条成功／失败汇总，不因一条外部错误丢掉其余结果。

#### Scenario: 100 条以内部分失败
- **WHEN** 批量查询 3 条且 1 条缺后单手机号
- **THEN** 返回 3 个结果；缺手机号的 case 保存 `tracking.status=query_failed` 与原因，因服务返回了结构化结果，批量项仍标 `success=true`；不存在或尚未寄出的 case 才计入批量失败项

### Requirement: 接力列表合并即时候选、case 与 binding

列表 MUST 合并三种 pair 集合去重：同设备当前重叠候选、已保存的运营 case、已确认 binding。无 case 而有 binding 的状态视 agreed；无两者的候选视 pending。前单已 completed 不展示；不再重叠且没有人工来源的纯 pending 不展示。人工来源由 `relay_case_manually_created` 审计记录识别，不依赖另一个数据库列。排序依次为计划寄出日、前单 ID、后单 ID；计划寄出日是前单 `end_date + 1 天`。每项带两位客户摘要、设备／型号、主次租赁组合与附件、顺丰摘要、`source` 和 `schedule_changed`。`open_total` 只统计当前筛选日期和状态内非 completed 的项。

#### Scenario: 已确认但档期不再重叠
- **WHEN** 某绑定对应的两单改期后不再成为即时候选
- **THEN** 列表仍保留 agreed pair，`schedule_changed=true`；单纯未保存的旧 pending 候选则消失

### Requirement: 列表筛选严格解析状态、日期和分页

`GET /api/relay-cases` MUST 接受重复 `statuses` 参数或逗号分隔状态，按首次出现去重；缺省为 `pending,notified,agreed,shipped`。起止日期缺省今天前 3 日和后 5 日，使用 `YYYY-MM-DD`；结束早于开始返回 400。`page`、`per_page` 必须为正整数，`per_page` 最大 100；响应有 `items,total,page,per_page,pages,open_total,filters`。未知状态、空状态筛选或非法分页都返回 400。

#### Scenario: 同时筛已完成与已寄出
- **WHEN** 请求 `statuses=completed,shipped` 且扩大日期窗口
- **THEN** 只显示这两阶段，`filters.statuses` 保持去重后的顺序，`open_total` 只数 shipped 项

### Requirement: 人工接力按设备挑最近的当前单和随后一单

人工候选 MUST 先限 active 主设备上的主租赁及有效寄出时间；对每台设备按寄出时间／ID 排序，取状态为 `shipped/returned` 的**最后一条**为当前单，再取其后第一条状态为 `not_shipped/scheduled_for_shipping` 的租赁为下一单。选项按设备名、ID 排序；已有同对绑定、前单已接给其他后单、后单已接自其他前单时分别给出 `blocked_reason`，而不是隐藏选项。人工创建再次锁前后单复核当前 pair，成功直接进入 agreed 并写审计；它可在无严格日期重叠时存在，区别于自动候选。

#### Scenario: 候选被另一单抢占
- **WHEN** 用户打开人工候选后，其他操作先绑定了该后单
- **THEN** 本次人工创建返回 409，不产生第二个绑定

### Requirement: 接力状态回退和重复寄出不能重复同步闲鱼

`PUT /api/relay-cases/<前>/<后>` MUST 允许五个状态中的任一目标状态；跨入 agreed 及以上时必须存在当前自动候选或已有人工作业／绑定，并创建不可分叉 binding；回退 pending/notified 时删除该 pair binding。首次从低于 shipped 进入 shipped 必须有顺丰号，内部状态和审计事务提交后才尝试闲鱼；同一 case 再次提交 shipped 或 completed 不应再次把前后租赁覆盖或重复触发闲鱼发货。若响应目标为 shipped，HTTP 处理器还会随即刷新一次顺丰轨迹并把 `tracking` 加入响应。

#### Scenario: 重复提交 shipped
- **WHEN** 一条已 shipped 的 case 再次提交 shipped 及相同运单号
- **THEN** 接力记录维持 shipped，不再次调用闲鱼发货；顺丰轨迹仍可刷新

### Requirement: 顺丰追踪失败写明确状态而不伪造妥投

追踪 MUST 仅对 shipped/completed 且已有单号的 case 执行；手机号去非数字后至少四位，并把后四位及后单租赁传顺丰服务。成功时保存状态、最近状态文字／轨迹备注／地址／时间去重拼接的最多 500 字摘要及 UTC 查询时间；返回完整轨迹。配置缺失、仓库无法唯一确定、缺后单电话或外部查询异常时保存 `query_failed`、具体安全错误摘要、空轨迹和查询时间，而不是标记已签收。批量 API 只把抛出的异常计作 `success=false`；被服务吸收为 `query_failed` 的条目仍是成功返回一条追踪记录。

#### Scenario: 仓库顺丰配置缺失
- **WHEN** shipped case 有单号而所在履约仓未配顺丰
- **THEN** 追踪状态保存 `query_failed` 和 `CONFIG_INCOMPLETE`，不生成虚构的物流节点

## 数据与 HTTP 契约

`rental_relay_cases`：唯一 `(predecessor_rental_id,successor_rental_id)`、两 ID 不相等、状态枚举、顺丰单号／状态／摘要／最后查询时间、四个里程碑及 UTC 时间戳。`rental_relay_bindings`：前单 ID 唯一、后单 ID 唯一、两 ID 不等、确认时间与时间戳；删除租赁时外键级联。case 是运营阶段，binding 是已确认不可分叉关系，两者不能当同一张表。

| 路径 | 行为 |
|---|---|
| `GET /api/relay-cases` | 可重复或逗号分隔 `statuses`；`ship_date_from,to,page,per_page` → 候选＋持久化 case／binding 的合并分页 |
| `GET /api/relay-cases/manual-options` | 当前单与下一单的可建／阻断原因 |
| `POST /api/relay-cases/manual` | `{device_id}` → 创建 agreed case 和 binding |
| `PUT /api/relay-cases/<predecessor_id>/<successor_id>` | `{status,sf_tracking_number?}` → case、追踪和闲鱼同步结果 |
| `POST /api/relay-cases/<case_id>/tracking/refresh` | 单条顺丰查询 |
| `POST /api/relay-cases/tracking/refresh-batch` | `{case_ids:[...最多100]}` → `{items,total,success_count}` |

PC `/relay-management` 与移动 `/mobile/relay` 均可查看候选、当前阶段和物流摘要；PC 支持人工标记与更新阶段。批量发货须读取 binding 并排除后单。

## 代码依据与验收

依据：`app/models/{rental_relay_case,rental_relay_binding}.py`、`app/services/relay/relay_case_service.py`、`app/routes/relay_case_api.py`、`app/handlers/relay_case_handlers.py`、`frontend/src/views/RelayManagementView.vue`、`frontend-mobile/src/views/RelayManagementView.vue`。验收覆盖候选日期严格性、绑定唯一、状态退回清里程碑、寄出内部事务与外部失败分离、人工候选并发、追踪逐条失败。
